# CI and Automated Security Regression Plan

This document records InkToCode's Phase 5 CI state. It turns the existing
quality and security regression suites into required, repeatable automation;
it does not claim that CI replaces deployment hardening or a production smoke
test.

## Workflow structure

.github/workflows/ci.yml uses six clearly separated jobs:

1. **Backend Fast** compiles Python, runs deterministic non-Docker backend
   tests, and checks changed-file whitespace.
2. **Frontend** installs from the lockfile, runs all frontend tests and ESLint,
   and produces a Next.js production build.
3. **Execution Security** builds the current runner image and runs the
   provider/static guards plus real adversarial Docker tests.
4. **Full Regression** builds the runner and runs the complete backend suite.
5. **Dependency Security** audits Python and npm dependency resolution.
6. **Secret Scan** scans the repository's tracked history with Gitleaks.

Every job has a descriptive name and independent failure output. Python and
npm downloads use the official setup-action caches. Docker layers, test
workspaces, generated content, and secrets are not cached.

## Pull-request checks

Every pull request runs Backend Fast, Frontend, Execution Security, Dependency
Security, and Secret Scan in parallel. Full Regression is intentionally
excluded because the dedicated isolation job already exercises the highest
risk Docker paths and the full backend suite takes roughly four to five
minutes after the runner is available.

The fast backend selection includes general API and AI boundary tests plus all
Phase 2 resource-protection, Phase 3 upload-security, and Phase 4 web-security
files. AI orchestration and behavioral C++ suites are not mislabeled as
non-Docker checks; they remain in Full Regression.

## Main-branch and manual checks

Pushes to main run all six jobs. Full Regression waits for Backend Fast,
Frontend, and Execution Security, then runs the complete backend suite with a
freshly built runner image. workflow_dispatch provides the same complete
pre-deployment CI run on demand.

Pushes to other branches are covered when they open or update a pull request.
There is no scheduled workflow: a nightly run would repeat the same
deterministic inputs without adding a distinct security signal.

## Docker execution-security verification

Execution Security builds runner/Dockerfile as inktocode-cpp-runner before
running:

~~~bash
pytest -q -rs tests/test_execution_providers.py tests/test_execution_security.py
~~~

These tests cover normal compilation and execution, non-root/read-only
execution, wall timeout, output limit, network isolation, filesystem/repository
isolation, application-environment isolation, PID limits, memory confinement,
compiler failure, result-file symlink rejection, Docker command restrictions,
the static host-process/compiler guard, capability probes, cleanup, and
fail-closed provider selection.

CI sets INKTOCODE_REQUIRE_DOCKER_TESTS=1. Under that explicit setting, an
unavailable daemon, missing runner image, or failed compiler capability probe
fails the test instead of being reported as an environment skip. Local
development retains the existing skip behavior when Docker is intentionally
unavailable.

## Dependency scan policy

The backend uses pip-audit 2.10.1 against backend/requirements.txt. pip-audit
does not expose a reliable severity threshold, so the backend gate fails for
any known advisory. This is intentionally stricter than the High/Critical
minimum and avoids inventing severity from incomplete metadata.

The frontend uses:

~~~bash
npm audit --audit-level=high
~~~

High and Critical npm advisories fail CI; Low and Moderate findings remain
visible without failing the job. During Phase 5, concrete High findings
required targeted updates to Next.js, PDF.js, and affected transitive
dependencies. The remaining DOMPurify advisory is Moderate, transitive through
Monaco, below the configured failure threshold, and should be removed when a
compatible upstream release resolves it.

No audit job automatically modifies dependencies.

## Secret scan policy

Gitleaks v8.27.0 scans the complete tracked Git history rather than relying on
PR comments or external paid services. Checkout uses full history and reports
are redacted. The only
allowlist entry requires both the exact Phase 4 logging-test path and its exact
synthetic sk-supersecret-that-must-not-be-logged sentinel. There are no broad
path, entropy, or rule suppressions.

The scanner receives a read-only repository mount. It receives no application
credentials, deployment credentials, or user content.

Git mode intentionally scans committed/tracked history and does not read
ignored local `.env` files. A local pre-deployment run must therefore target
the exact reviewed commit; the push workflow then scans that commit before it
can be deployed. Phase 5 additionally validated a temporary snapshot of all
currently tracked and non-ignored worktree files.

## Dependabot policy

Dependabot checks pip (/backend), npm (/frontend), and GitHub Actions (/)
weekly on Monday in the project timezone. Open version-update pull requests are
bounded to three each for pip/npm and two for Actions. Dependency changes still
have to pass the same CI jobs; Dependabot does not auto-merge them.

Repository administrators must enable Dependabot alerts and security updates
in GitHub repository settings if they are not already enabled. The committed
configuration cannot enable those account-level settings by itself.

## Workflow security

The workflow has only contents: read permission. It does not use
pull_request_target, write permissions, deployment environments, or
repository/application secrets. Fork pull requests therefore run without
Gemini or deployment credentials. PR-controlled titles, branch names, paths,
or body text are never interpolated into shell commands. Changed-file SHAs are
passed through environment variables and are generated by GitHub.

Checkout, Python, and Node actions use stable major release tags. Scanner and
audit tool versions are pinned to specific releases. Dependabot covers future
GitHub Action updates.

## GitHub-hosted runner limitations

The isolation job verifies Docker behavior on GitHub's Ubuntu x86-64 hosted
kernel. It does not prove behavior for a future deployment provider's kernel,
container runtime, filesystem driver, cgroup configuration, reverse proxy, or
network edge. Those must be checked during deployment and the production smoke
test.

The job does verify the controls GitHub-hosted Docker can enforce: no network,
non-root user, read-only root filesystem, dropped capabilities,
no-new-privileges, CPU/memory/PID limits, mount isolation, time/output limits,
cleanup, and sanitizer/Valgrind capability. A missing required capability
fails closed.

## Expected runtime

With warm package caches, expected GitHub-hosted runtimes are approximately:

- Backend Fast: 1–2 minutes including dependency installation
- Frontend: 1–3 minutes including npm ci and production build
- Execution Security: 3–7 minutes including the runner build
- Dependency Security: 1–3 minutes, network dependent
- Secret Scan: under 2 minutes after image pull
- Full Regression: 6–10 minutes including a separate runner build

Pull-request wall time should normally be dominated by Execution Security.
Main/manual runs take longer because Full Regression starts only after the
primary correctness and isolation gates pass.

## Local reproduction

From the repository root, build the same runner used by CI:

~~~bash
docker build --tag inktocode-cpp-runner ./runner
~~~

Run backend checks:

~~~bash
cd backend
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m compileall app
INKTOCODE_REQUIRE_DOCKER_TESTS=1 pytest -q -rs \
  tests/test_execution_providers.py tests/test_execution_security.py
pytest -q
~~~

Run frontend checks:

~~~bash
cd frontend
npm ci
npm test
npm run lint
npm run build
npm audit --audit-level=high
~~~

Run dependency and secret checks from the relevant directories:

~~~bash
cd backend
python -m pip install pip-audit==2.10.1
pip-audit -r requirements.txt --progress-spinner=off
~~~

~~~bash
docker run --rm \
  --volume "$PWD:/repo:ro" \
  ghcr.io/gitleaks/gitleaks:v8.27.0 \
  git --config=/repo/.gitleaks.toml --redact --no-banner --no-color /repo
git diff --check
~~~

The Gitleaks command assumes the current directory is the repository root and
scans committed content. Run it against the exact release commit; CI repeats
the scan after push. None of these tests requires a real Gemini key; external
AI calls are mocked.

## Final pre-deployment regression

Immediately before deployment:

1. Start Docker and build inktocode-cpp-runner from the current checkout.
2. Install backend development dependencies, compile app, and run the
   Docker-required Phase 1 files.
3. Run the complete backend pytest -q suite.
4. Run frontend npm ci, npm test, npm run lint, and npm run build.
5. Run pip-audit and npm audit --audit-level=high.
6. Run git diff --check, review git status, and create the exact release commit.
7. Run the pinned Gitleaks scan on that commit, push it, and require all GitHub
   CI jobs to pass, including the repeated full-history secret scan.
8. Deploy that revision, then perform the production CORS/header, upload,
   transcription, compile, execution-isolation, timeout, and error-correlation
   smoke tests.

Deployment and its production smoke test are the only remaining engineering
steps. Strix, staging pentest infrastructure, and external pentesting are not
part of this plan.
