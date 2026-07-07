"""Sentry must only initialize when `SENTRY_DSN` is configured (main.py).

`sentry_sdk.init(...)` used to run unconditionally at import time with a
hardcoded DSN. Now it is gated behind `os.environ.get("SENTRY_DSN")`.

`main.py` calls `sentry_sdk.init` at *module import* time, and Python only
imports a module once per process — by the time this test file runs, other
test modules have almost certainly already imported `main` (with `SENTRY_DSN`
unset by the `client`/`app` fixtures' own env). To get a clean, deterministic
read on "did init() run", each case imports `main` fresh in a subprocess.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap


def _run_main_import_probe(*, sentry_dsn: str) -> str:
    """Import main.py in a fresh subprocess and report Sentry's init state."""
    script = textwrap.dedent(
        """
        import os
        os.environ["ENVIRONMENT"] = "development"
        os.environ["JWT_SECRET_KEY"] = "ci-strong-secret-key-that-is-long-enough-xxxx"

        import sentry_sdk
        import main  # noqa: F401  (triggers the module-level sentry_sdk.init gate)

        print("INITIALIZED" if sentry_sdk.is_initialized() else "NOT_INITIALIZED")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=__file__.rsplit("/tests/", 1)[0],
        env={**_base_env(), "SENTRY_DSN": sentry_dsn},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"subprocess failed: {result.stderr}"
    return result.stdout.strip().splitlines()[-1]


def _base_env() -> dict:
    import os

    return dict(os.environ)


class TestSentryGatedByDsn:
    def test_no_dsn_does_not_initialize_sentry(self):
        outcome = _run_main_import_probe(sentry_dsn="")
        assert outcome == "NOT_INITIALIZED"

    def test_dsn_present_initializes_sentry(self):
        # A syntactically valid (but fake) DSN — sentry_sdk.init() only
        # validates the DSN format locally, it never makes a network call.
        outcome = _run_main_import_probe(
            sentry_dsn="https://public@o0.ingest.sentry.io/0"
        )
        assert outcome == "INITIALIZED"
