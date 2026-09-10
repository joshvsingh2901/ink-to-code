# Execution Security Plan — Phase 1

## Security invariant

The FastAPI application process and host never directly compile or execute
user-submitted C++. Every compile and run request must cross the Docker runner
boundary. If Docker or the fixed runner image is unavailable, the operation
fails closed; there is no host fallback.

> **Developer rule:** Do not add `subprocess` compiler or executable launches
> to API services. Extend `DockerExecutionProvider` and the fixed runner
> protocol instead.

## Prior architecture and findings

The repository had two execution architectures:

| Request path | Prior compile | Prior execution | Prior isolation |
| --- | --- | --- | --- |
| `POST /api/compile` | `compiler.compile_cpp` called host `g++ -fsyntax-only` | none | host temporary directory only |
| `POST /api/run-tests`, normal program mode | `test_execution._compile_executable` called host `g++` | `_run_process` called the host binary with `Popen` | host timeout/output polling only |
| function/manual tests | deterministic harness, then host `g++` | same host `_run_process` | host timeout/output polling only |
| object/inheritance/operator/iterator/template/exception scenarios | deterministic harness, then host `g++` | same host `_run_process` | host timeout/output polling only |
| AI-generated tests | `compile_cpp`, then `run_test_request` | inherited the normal host path | host |
| Rerun Same Tests | `compile_cpp`, then `run_test_request` | inherited the normal host path | host |
| memory diagnostics | Docker only when selected and available; `auto` could fall back | Docker or host sanitizer path | conditional |
| sanitizer capability probes | host compiler and host probe binaries | host | none |

The direct host paths used fixed argument arrays and `shell=False`; source text
was written to server-generated filenames and was not interpolated into a
command. No shell-command injection was found. The primary vulnerability was
architectural: a malicious or exploited student binary ran with the API host's
OS identity, filesystem visibility, network access, process namespace, and
environment. Host compiler parsing was also outside an isolation boundary.

The older Docker runner already used a non-root account, no network, a
read-only root filesystem, dropped capabilities, `no-new-privileges`, CPU,
memory, PID, timeout, and output settings. It was limited to memory checks,
however, and `auto` explicitly fell back to the host. Its in-container process
capture could also buffer unbounded output before truncating it.

## Final architecture

All paths now converge on `DockerExecutionProvider`:

```text
POST /api/compile
  -> compiler.compile_cpp
  -> DockerExecutionProvider.compile_source
  -> disposable runner container
  -> fixed g++ C++17 syntax-only command

POST /api/run-tests
  -> test_execution.run_test_request
  -> deterministic program/function/object harness generation
  -> DockerExecutionProvider.compile_and_run(compile_only=True)
  -> fixed in-container C++17 compiler command
  -> DockerExecutionProvider.compile_and_run for each explicit test
  -> fixed in-container executable path

POST /api/ai-tests/run and /api/ai-tests/rerun
  -> isolated compile_cpp preflight
  -> existing generation/revalidation logic
  -> the same run_test_request boundary above
```

Function variants, arrays, vectors, strings, multiple mutable outputs,
iterators/STL algorithms, templates, exceptions, object/operator scenarios,
inheritance/polymorphism, and Big Five behavior are harness-generation modes
inside `run_test_request`; none has a separate process launcher. Memory checks
use the same provider with sanitizer/Valgrind mode enabled. The only backend
`subprocess.run` sites launch the fixed Docker CLI or inspect Docker readiness;
the API host contains no compiler invocation and no user-binary `Popen` path.

## Trust boundaries and runner restrictions

The API validates requests and generates harness source. A unique host
temporary directory contains only the current generated source, fixed runner
manifest, compiler output binary, and bounded sidecar results. Only that
directory is bind-mounted at `/work`; the repository, home directory, Docker
socket, `.env`, and application secrets are not mounted. Docker does not pass
the API process environment into the container.

Every disposable container has:

- user `runner` (UID 10001), never root;
- `--network none` and a private IPC namespace;
- read-only root filesystem;
- all Linux capabilities dropped;
- `no-new-privileges` and Docker's default seccomp policy;
- no privileged mode and no Docker socket mount;
- CPU, memory, equal memory+swap, and PID limits;
- zero-byte core dumps, 64 MiB per-file limit, and 64-open-file limit;
- a fixed, non-executable 16 MiB `/tmp` tmpfs;
- a fixed image, compiler command, source name, executable name, working
  directory, and environment;
- an internal compile timeout and per-run wall-clock timeout;
- active 64 KiB stdout/stderr monitoring that kills the process group on
  overflow;
- bounded sidecar parsing and path redaction;
- forced container removal on outer timeout;
- `TemporaryDirectory` cleanup on every API success or failure path.

The normal product execution timeout remains 2 seconds. The output contract
remains 64 KiB. Backend-only configuration caps the container compile and run
timeouts; frontend input cannot set Docker flags, compiler flags, image names,
mounts, executable paths, environments, or resource limits.

## Failure semantics

- User compile errors remain normal successful API responses with the real,
  bounded compiler stderr and parsed diagnostics.
- Compile wall-time exhaustion maps to `compiler_timeout`.
- A missing Docker daemon/image, invalid runner result, or container startup
  failure maps to `runner_unavailable` for normal compile/run requests.
- Per-test wall timeout remains a failed test with `timed_out=true`.
- Output overflow remains a failed test with `output_limited=true` and bounded
  raw output.
- Runtime nonzero exits/signals remain failed tests with stderr and exit code.
- Container resource termination is confined to the disposable container; a
  missing result after an exit-137 runtime is reported as an isolation-limit
  runtime failure where Docker exposes that status.
- Memory-runner capability/infrastructure failures retain the existing
  `memory_status=unavailable` contract and never fall back to host execution.

## Verification

Deterministic tests validate command construction, `shell=False`, mandatory
Docker selection, fail-closed host configuration, resource flags, container
cleanup after outer timeout, compile routing, test routing, and the runner
protocol. Real Docker tests validate:

- valid syntax compilation and normal execution;
- non-root execution and read-only root filesystem;
- infinite-loop termination;
- 64 KiB output enforcement;
- blocked external network connection;
- inability to read an API-host marker or application path;
- non-propagation of an API-host environment secret;
- PID-limit enforcement against fork fanout;
- memory exhaustion confinement followed by a healthy runner request;
- preservation of real compiler diagnostics.

AI generation and Rerun Same Tests call the same `run_test_request` function as
manual tests. Existing end-to-end AI, function, object, inheritance, iterator,
exception, template, Big Five, and memory tests exercise that shared route.

## Performance

On the Phase 1 development machine with a warm Docker image, comparable
single-process wall-clock commands measured:

| Operation | Before | After |
| --- | ---: | ---: |
| simple syntax compile | 1.01 s | 0.46 s |
| simple one-case manual run | 1.07 s | 0.83 s |

Image build/pull time and a cold Docker Desktop startup are deployment/setup
costs, not interactive request latency. The implementation reuses one compiled
binary across test cases in a request while retaining a disposable container
for each execution.

## Residual risks

- The runner relies on the Docker daemon and Docker's kernel/container boundary;
  it is not a VM-grade or formally verified sandbox.
- The unique `/work` bind mount is writable so binaries and harness sidecars can
  persist between disposable compile/run containers. It exposes no application
  files, but the per-file `ulimit` is not an aggregate directory quota. A
  dedicated tmpfs/volume quota or stronger runner substrate should replace it
  before hostile multi-tenant internet exposure.
- The per-request `/work` tempdir is `chmod 0o777` on the API host so the
  container's non-root uid can write `program` and `runner-result.json` back
  to it. This is a host-local tampering surface, not a remote one: a local
  unprivileged user on the API host could race to replace
  `runner-result.json` or plant a symlink there while a request is in flight.
  It does not expose application files or break container isolation. Matching
  container/host uids, or a dedicated runtime user for the API process, is
  the deployment-side mitigation; this repository change adds a symlink
  guard on the result read as a narrower code-level mitigation.
- The Docker CLI remains available to the API host service account because the
  backend must start runner containers. The socket is never mounted into a
  runner. Production deployment should isolate the runner control plane from
  the web process more strongly.
- Docker image provenance, digest pinning, vulnerability scanning, daemon
  authorization, seccomp/AppArmor customization, monitoring, and security
  patch operations require deployment policy beyond this repository change.
- Per-request container creation is isolated but not globally rate-limited.

## Deferred to Phase 2+

Authentication, rate limiting, global concurrency/queue controls, aggregate
disk quotas, production scheduler selection, dedicated worker hosts, VM or
microVM isolation, deployment-provider changes, observability/alerting, image
supply-chain policy, CORS/security headers, and broader upload hardening remain
out of scope for Phase 1.
