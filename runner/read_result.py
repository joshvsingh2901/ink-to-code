"""Root-side reader for /work/runner-result.json.

Runs as root inside the sandbox (outside the non-root user's process),
specifically so it can read a file written by the non-root user without
ever trusting a symlink that user-controlled code might have planted at the
expected result path. Opens the path with O_NOFOLLOW so a symlink there
causes the open itself to fail rather than silently following it off
/work, then verifies the descriptor really refers to a regular file before
reading it. Bounded to 64 KiB, matching the runner's own output cap.

On any failure -- missing file, symlink, not a regular file, oversized,
unreadable, anything -- this prints the JSON text "{}" and exits cleanly.
It never raises, so its caller can always treat stdout as a JSON document.

MAX_BYTES bounds the whole result *file*, not any single field in it --
runner.py's own bounded() caps each of up to three independent streams
(stdout, stderr, and, in memory-diagnostics mode, valgrind_diagnostics --
see runner.py's calls to bounded()) at 64 KiB of raw bytes each, and a
legitimate result JSON can carry all three at once. json.dumps's default
ensure_ascii=True escapes each non-ASCII replacement character introduced
by errors="replace" decoding as a 6-byte \\uXXXX sequence, so one 64 KiB
raw field can expand to ~384 KiB of JSON text in the worst case (arbitrary
binary output); three such fields is ~1.15 MiB. This cap is sized well
above that legitimate worst case -- it still firmly bounds the read
against a truly oversized/corrupted file, it just isn't set to the same
64 KiB figure as the runner's own per-stream output cap, which a
multi-field legitimate result can exceed.
"""

import os
import stat


RESULT_PATH = "/work/runner-result.json"
MAX_BYTES = 2 * 1024 * 1024


def read_result(path: str | None = None, limit: int = MAX_BYTES) -> str:
    if path is None:
        path = RESULT_PATH
    fd = None
    try:
        # O_NONBLOCK matters only for a FIFO (a regular file ignores it):
        # without it, opening a pipe with no writer connected would hang
        # this reader forever instead of failing fast into the S_ISREG
        # check below, which rejects it as not a regular file anyway.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return "{}"
        # Regular files ignore O_NONBLOCK for reads/writes, but clear the
        # flag anyway so read() below behaves exactly like a normal
        # blocking read on the (already known regular) file.
        os.set_blocking(fd, True)
        data = os.read(fd, limit)
        # Read one extra byte to detect (without loading it) whether the
        # file exceeds the cap; if so, treat it the same as any other
        # failure rather than returning truncated JSON.
        if len(data) >= limit and os.read(fd, 1):
            return "{}"
        return data.decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return "{}"
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass


def main() -> None:
    print(read_result())


if __name__ == "__main__":
    main()
