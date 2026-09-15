# Modal execution provider: deployment guide

InkToCode's isolated C++ execution has two interchangeable providers behind
the `ExecutionProvider` interface (`backend/app/services/execution_providers.py`):

- **Docker** (`CPP_EXECUTION_PROVIDER=docker`, the local default) — a
  hardened `docker run` of the `runner/` image on whatever host runs the
  API.
- **Modal** (`CPP_EXECUTION_PROVIDER=modal`) — an isolated, non-root,
  network-disabled, gVisor-backed ephemeral cloud sandbox running the
  *same* `runner/` image, for deployments where the API host cannot itself
  run privileged Docker containers (most PaaS hosts, including Render).

Both providers run the exact same `runner/runner.py` unmodified. Only the
launch mechanism differs. This document covers everything specific to the
Modal path: environment variables, Modal token creation, publishing and
rolling back the runner image, the live security-test procedure, cost
guardrails, and the Modal SDK surface this integration was built and
pinned against.

## 1. Environment variables

Set these in `backend/.env` (see `backend/.env.example` for the blank
template) or in your deployment platform's environment/secrets store.
`MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET` are read directly by the `modal`
SDK from the process environment (standard Modal convention) — they are
**not** read by `app/config.py`, so they need no application-level wiring
beyond being present in the process environment.

| Variable | Read by | Required for `modal` | Notes |
| --- | --- | --- | --- |
| `CPP_EXECUTION_PROVIDER` | `app/config.py` | must be `modal` | default is `docker`; `auto`/`docker`/`modal` are the only accepted values, `host` is always rejected |
| `MODAL_TOKEN_ID` | `modal` SDK directly | yes | from a Modal API token (see §2) |
| `MODAL_TOKEN_SECRET` | `modal` SDK directly | yes | from a Modal API token (see §2); never logged, never echoed into any diagnostic |
| `MODAL_APP_NAME` | `app/config.py` | no (default `inktocode-cpp-runner`) | the Modal `App` sandboxes are created under; `App.lookup(..., create_if_missing=True)` |
| `MODAL_RUNNER_IMAGE` | `app/config.py` | yes | the published GHCR image reference, **pinned to a digest** (`ghcr.io/<owner>/<repo>/inktocode-cpp-runner@sha256:...`), never `:latest`, in any environment that isn't purely local experimentation |
| `MODAL_SANDBOX_TIMEOUT_SECONDS` | `app/config.py` | no (default `600`) | hard sandbox lifetime cap passed to `Sandbox.create(timeout=...)` |
| `MODAL_SANDBOX_IDLE_TIMEOUT_SECONDS` | `app/config.py` | no (default `120`) | idle-teardown backstop passed to `Sandbox.create(idle_timeout=...)`, in case `provider.close()` is ever missed |

`_validated_settings()` in `execution_providers.py` fails closed at
provider-selection time if `CPP_EXECUTION_PROVIDER=modal` and
`MODAL_RUNNER_IMAGE` is empty — it does not fall through to Docker.

`CPP_RUNNER_MEMORY` and `CPP_RUNNER_CPUS` (already used by the Docker
path) are reused for Modal too — `ModalExecutionProvider` parses them into
the `(cpu, cpu)` / `(memory_mib, memory_mib)` tuples `Sandbox.create()`
expects, via `_memory_mib()` in `modal_provider.py` (`"256m"` → `256`,
`"1g"` → `1024`). There are no separate Modal-specific resource-size
variables.

## 2. Creating a Modal API token

1. Sign in at <https://modal.com> with the account that owns (or will own)
   the `inktocode-cpp-runner` Modal App.
2. Create a token: **Settings → API Tokens → New Token** (or `modal token
   new` from the `modal` CLI, which writes `~/.modal.toml` locally — for
   deployment you want the raw `MODAL_TOKEN_ID`/`MODAL_TOKEN_SECRET` pair,
   not the CLI's local config file).
3. Store the two values as deployment secrets (Render environment group,
   GitHub Actions secret store for any workflow that needs to run live
   Modal tests, etc.) — never commit them, never put them in
   `backend/.env` outside of a developer's own untracked local file.
4. Scope: a token scoped to a single Modal workspace/environment is
   sufficient; InkToCode never needs organization-admin Modal permissions.

## 3. Publishing the runner image to GHCR

The `runner-image` CI job (`.github/workflows/ci.yml`) builds `runner/`
and pushes it to GHCR on every push to `main`, tagged both `:<git-sha>`
and `:latest`, and writes the resulting digest to the job summary. To
publish manually:

```bash
docker build -t ghcr.io/<owner>/<repo>/inktocode-cpp-runner:$(git rev-parse HEAD) ./runner
docker push ghcr.io/<owner>/<repo>/inktocode-cpp-runner:$(git rev-parse HEAD)
docker inspect --format='{{index .RepoDigests 0}}' ghcr.io/<owner>/<repo>/inktocode-cpp-runner:$(git rev-parse HEAD)
```

Set `MODAL_RUNNER_IMAGE` to the **digest** form
(`ghcr.io/<owner>/<repo>/inktocode-cpp-runner@sha256:...`), not a mutable
tag — `ModalExecutionProvider` builds its sandbox image exclusively via
`modal.Image.from_registry(settings.modal_runner_image)`, with no
`run_commands`/`pip_install`/`apt_install` layered on afterward, so
pinning to a digest is the only way to guarantee the exact bytes Modal
pulls match what CI tested.

### Rollback

Because every deploy pins a digest, rollback is just re-pointing
`MODAL_RUNNER_IMAGE` at a previous digest (visible in GHCR's package
version history, or a prior CI job summary) and restarting the API
process — no image rebuild or re-push required. `modal_capabilities()` is
`lru_cache`d per `(image, cpu, memory, sandbox_timeout)` tuple, so a
digest change is picked up on process restart.

## 4. Live security-test procedure

`backend/tests/test_modal_integration.py` ports the Docker security
corpus (`test_execution_security.py`) to the Modal path. It is marked
`modal_live` and skipped by default everywhere (`pytest.ini`'s
`addopts = -m "not modal_live"`); it is **not** run as part of this
migration and must not be run without real Modal credentials.

To run it before trusting the Modal path in production:

```bash
cd backend
export MODAL_TOKEN_ID=...
export MODAL_TOKEN_SECRET=...
export MODAL_RUNNER_IMAGE=ghcr.io/<owner>/<repo>/inktocode-cpp-runner@sha256:...
export INKTOCODE_RUN_MODAL_TESTS=1
.venv/bin/python -m pytest -m modal_live tests/test_modal_integration.py -q -rs
```

This is the gate for the specific risks the migration explicitly could
not verify offline (see §6 and AGENTS.md's security matrix):

- **non-root execution is real under the sandbox runtime** — the Modal
  sandbox container runs as root and ignores a Dockerfile `USER`
  directive; the compensating `setpriv --reuid=10001` step in the fixed
  launch command must actually drop privileges before user code runs.
- **the PID limit (`ulimit -u 32`) is enforced under gVisor** — unlike
  Docker's native `--pids-limit`, this is unverified until a live fork
  fanout test proves it.
- **network really is blocked** (`block_network=True`) against a real
  external address, not just asserted as a sandbox kwarg.
- **no host/platform secret is visible to user code**, including
  `MODAL_TOKEN_SECRET` itself.
- **the symlink guard on the result path holds under a real sandbox
  filesystem** — a program that replaces `/work/runner-result.json` with
  a symlink must not have `read_result.py` follow it.
- **`modal_capabilities()` proves ASan + UBSan + a working leak tool**
  against the actual published image, not just against the mocked
  capability-probe payload shape.

Do not treat the mocked suite (`test_modal_provider.py`) as a substitute
for this — it proves the code calls the SDK correctly; it cannot prove
gVisor enforces what the kwargs ask for.

## 5. Cost guardrails

- `modal_capabilities()` is `lru_cache`d (`maxsize=4`) — repeated capability
  checks within a process do not spawn repeated probe sandboxes.
- Exactly one sandbox is created per compile-and-test HTTP request
  (`ModalExecutionProvider` binds to one `work_directory` and raises if
  reused with a different one) and reused across that request's compile
  and all of its test runs — never pooled or kept warm across requests.
- Every sandbox is torn down in a `finally` (`compiler.py`,
  `test_execution.py`'s `run_test_request`) via `provider.close()` →
  `sandbox.terminate()`, backstopped by `MODAL_SANDBOX_IDLE_TIMEOUT_SECONDS`
  (default 120s) in case `close()` is ever missed (a crash between
  creation and the `finally`, for instance).
- `MODAL_SANDBOX_TIMEOUT_SECONDS` (default 600s) is a hard per-sandbox
  ceiling independent of the idle timeout.
- Keep an eye on Modal's dashboard for sandbox-minute usage after
  enabling this in production; the defaults above are conservative but
  this integration has not yet been load-tested against real traffic.

## 6. Modal SDK surface this integration is pinned against

Captured directly from the installed `modal==1.5.5` package (`modal>=1.5,<2`
in `backend/requirements.txt`) via `inspect.signature`, per the
implementation spec's Step I. Record here so a future SDK bump can diff
against what this code actually relies on.

```
modal.Sandbox.create(*args, app=None, name=None, tags=None, image=None,
    env=None, secrets=None, network_file_systems={}, timeout=300,
    idle_timeout=None, workdir=None, gpu=None, cloud=None, region=None,
    cpu=None, memory=None, block_network=False,
    outbound_cidr_allowlist=None, outbound_domain_allowlist=None,
    inbound_cidr_allowlist=None, volumes={}, pty=False, encrypted_ports=[],
    h2_ports=[], unencrypted_ports=[], custom_domain=None, proxy=None,
    include_oidc_identity_token=False, readiness_probe=None, verbose=False,
    experimental_options=None, ...) -> Sandbox

modal.Sandbox.exec(*args, stdout=StreamType.PIPE, stderr=StreamType.PIPE,
    timeout=None, workdir=None, env=None, secrets=None, text=True,
    bufsize=-1, pty=False, ...) -> ContainerProcess

modal.Sandbox.terminate(*, wait=False) -> int | None
modal.Sandbox.open(path, mode="r") -> FileIO   # used only to WRITE inputs
modal.Sandbox.rm(path, recursive=False) -> None
modal.Sandbox.mkdir(path, parents=False) -> None

modal.Image.from_registry(tag, secret=None, *,
    setup_dockerfile_commands=[], force_build=False,
    add_python=None, **kwargs) -> Image

modal.App.lookup(name, *, client=None, environment_name=None,
    create_if_missing=False) -> App

# ContainerProcess (the return value of Sandbox.exec):
#   .wait() -> int             (blocks until the process exits)
#   .returncode                (set after wait())
#   .stdout / .stderr          -> StreamReader, with .read() -> str
#   .stdin

# Relevant exception types (modal.exception):
#   ExecTimeoutError, SandboxTimeoutError, SandboxTerminatedError,
#   SandboxFilesystemNotFoundError, SandboxFilesystemPermissionError
```

### Findings that shaped `modal_provider.py`

- **`sb.open()` vs `sb.filesystem.*`**: this pinned version exposes
  `Sandbox.open`/`Sandbox.rm`/`Sandbox.mkdir` directly on the `Sandbox`
  object (no separate `.filesystem` namespace). `modal_provider.py` uses
  `sandbox.open(path, "wb"/"w")` as a context manager to **write** inputs
  (`main.cpp`, `runner-request.json`) only. It is never used to read the
  result — see the symlink-safety note below.
- **Reading results never uses `sb.open()`**: `Sandbox.open()`'s read path
  was not verified to reject a symlink the way `read_result.py`'s
  `O_NOFOLLOW` does, and the implementation spec was explicit that it must
  not be trusted for this. Every result read goes through
  `sandbox.exec("python3", "/opt/inktocode/read_result.py", ...)` and its
  stdout instead — the same root-side, symlink-safe reader added to the
  runner image in this migration.
- **No exposed `chmod`**: neither `Sandbox` nor the `file_io` module in
  this SDK version exposes a permission-bit-setting call. The Docker path
  explicitly `chmod`s host-seeded inputs to `0644`; the Modal path cannot
  reproduce that exact permission bit through the public SDK surface as
  written. This is a **known, unverified gap** — `_upload_inputs()` writes
  files through the sandbox filesystem API's default behavior and relies
  on the non-root `setpriv` user simply not owning the files it reads
  (rather than an explicit read-only permission bit). Confirm this
  produces the intended "non-root user can read but not overwrite"
  invariant with a live test before depending on it; do not assume parity
  with Docker's explicit `chmod 0644` here.
- **`ContainerProcess.stdout.read()` blocks until stream end**: unlike a
  live-tailing iterator, `StreamReader.read()` returns the full captured
  text once available, which is what `modal_provider.py` relies on after
  `.wait()` — reading before/without `.wait()` was not exercised and is
  not how this code calls it.
- **Timeout signaling**: `modal.exception.ExecTimeoutError` and
  `SandboxTimeoutError` both exist and are the two exception types
  `modal_provider.py` catches to detect an exec-level timeout (vs. a
  generic infrastructure failure) and trigger `provider.close()`. Whether
  these are *actually* what a real gVisor timeout raises (as opposed to,
  say, a plain `TimeoutError` or a hang) is **unverified** — this is
  exactly what R5 in the migration's risk list flags as "verify before
  deploy, not now." The live integration suite's timeout test
  (`test_infinite_loop_is_terminated_by_wall_timeout`) is the gate.
- **Synchronicity + threadpool**: this SDK wraps an async implementation
  with `synchronicity` to present a synchronous API; FastAPI calls this
  provider from a Starlette threadpool thread (the same pattern already
  used for the Docker provider's blocking `subprocess.run`). This was not
  independently verified as safe under load here — see R5 in the
  migration's known risks.

## 7. Honest security matrix

See `AGENTS.md`'s "Isolated C++ execution" section and the table in
`README.md`'s "Execution Safety" section for the full, per-control Docker
vs. Modal comparison, including exactly which controls are equivalent,
which are compensating, and which are real gaps. Do not repeat or
reference this integration elsewhere without preserving that same honesty
— in particular, never describe the Modal path as providing read-only
rootfs, Linux capability dropping, or a *proven* PID limit; those claims
are either false or unverified pending the live test procedure in §4.
