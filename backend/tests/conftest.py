"""Test-wide environment defaults applied before application imports."""

import os


# Rate-limiter behavior has focused tests with explicit enabled settings. Keep
# the shared application from coupling unrelated endpoint tests through a
# process-local quota.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")
