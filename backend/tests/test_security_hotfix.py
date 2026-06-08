"""Regression tests for the Phase-1 account-takeover hotfix (EPIC-SEC).

Covers:
  SEC-ATO-1  .env.example templates use the real variable names.
  SEC-ATO-2  fail-closed JWT_SECRET_KEY guard (validator + boot) and that a
             token forged with the public default is rejected.
  SEC-ATO-3  POST /auth/request-reset never leaks the reset token in the body
             or logs, and responds identically for known/unknown emails.

These tests are import-light where possible: the config/forged-token tests only
touch `config` + `jose`; the endpoint tests import `main` with a strong secret
in the environment so the boot-guard passes.
"""
import logging
import os

import pytest

from conftest import STRONG_SECRET

WEAK_DEFAULT = "change-me-in-production"
ANOTHER_WEAK = "your-secret-key-here"


# ---------------------------------------------------------------------------
# SEC-ATO-1 — .env.example templates document the real variable names
# ---------------------------------------------------------------------------

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_BACKEND_DIR = os.path.join(_REPO_ROOT, "backend")
ENV_EXAMPLES = [
    os.path.join(_REPO_ROOT, ".env.example"),
    os.path.join(_BACKEND_DIR, ".env.example"),
]
FORBIDDEN = ["SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY", "DATABASE_URL"]


@pytest.mark.parametrize("path", ENV_EXAMPLES)
def test_env_example_has_no_forbidden_names(path):
    content = open(path, encoding="utf-8").read()
    for name in FORBIDDEN:
        assert name not in content, f"{path} still references {name}"
    # `JWT_SECRET` without the `_KEY` suffix must not appear as a key.
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        assert key != "JWT_SECRET", f"{path} uses bare JWT_SECRET (must be JWT_SECRET_KEY)"


@pytest.mark.parametrize("path", ENV_EXAMPLES)
def test_env_example_has_required_names(path):
    content = open(path, encoding="utf-8").read()
    for name in ("SUPABASE_URL", "SUPABASE_KEY", "JWT_SECRET_KEY"):
        assert f"{name}=" in content, f"{path} is missing {name}="


# ---------------------------------------------------------------------------
# SEC-ATO-2 — JWT_SECRET_KEY validator: strong accepted / default rejected
# ---------------------------------------------------------------------------

def _make_settings(jwt_secret, environment):
    import config

    return config.Settings(JWT_SECRET_KEY=jwt_secret, ENVIRONMENT=environment)


def test_validator_accepts_strong_secret_in_production():
    settings = _make_settings(STRONG_SECRET, "production")
    assert settings.JWT_SECRET_KEY == STRONG_SECRET


@pytest.mark.parametrize("weak", ["", WEAK_DEFAULT, ANOTHER_WEAK, "short"])
def test_validator_rejects_weak_secret_in_production(weak):
    with pytest.raises(RuntimeError):
        _make_settings(weak, "production")


def test_validator_rejects_31_char_secret_in_production():
    with pytest.raises(RuntimeError):
        _make_settings("a" * 31, "production")


def test_validator_accepts_exactly_32_chars_in_production():
    settings = _make_settings("a" * 32, "production")
    assert len(settings.JWT_SECRET_KEY) == 32


@pytest.mark.parametrize("weak", ["", WEAK_DEFAULT, ANOTHER_WEAK, "short"])
def test_validator_only_warns_outside_production(weak, caplog):
    with caplog.at_level(logging.WARNING, logger="harven"):
        settings = _make_settings(weak, "development")
    assert settings.JWT_SECRET_KEY == weak  # boot proceeds, no exception
    assert any("JWT_SECRET_KEY" in r.message for r in caplog.records)


def test_boot_fail_closed_in_production_with_weak_secret(monkeypatch):
    """get_settings() at boot must raise in production with the public default."""
    import config

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", WEAK_DEFAULT)
    config.get_settings.cache_clear()
    with pytest.raises(RuntimeError):
        config.get_settings()


def test_boot_succeeds_in_production_with_strong_secret(monkeypatch):
    import config

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", STRONG_SECRET)
    config.get_settings.cache_clear()
    settings = config.get_settings()
    assert settings.JWT_SECRET_KEY == STRONG_SECRET


def test_forged_token_with_default_is_rejected_under_strong_secret():
    """A token signed with the public default fails to decode under a strong key.

    In production the boot-guard guarantees the running secret is strong, so a
    token forged with "change-me-in-production" is rejected — surfacing as 401
    in auth.get_current_user (which raises HTTP 401 on JWTError).
    """
    from jose import JWTError, jwt

    forged = jwt.encode({"sub": "victim", "role": "ADMIN"}, WEAK_DEFAULT, algorithm="HS256")
    with pytest.raises(JWTError):
        jwt.decode(forged, STRONG_SECRET, algorithms=["HS256"])


# ---------------------------------------------------------------------------
# SEC-ATO-3 — request-reset must not leak the token (body or log)
# ---------------------------------------------------------------------------

class _FakeQuery:
    """Minimal fluent stub for the Supabase query builder used by the endpoint."""

    def __init__(self, data):
        self._data = data

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        class _Res:
            pass

        r = _Res()
        r.data = self._data
        return r


class _FakeClient:
    def __init__(self, user_row):
        self._user_row = user_row

    def table(self, _name):
        return _FakeQuery(self._user_row)


@pytest.fixture
def reset_client(monkeypatch):
    """Import `main` with a strong secret + non-prod, RESET_TOKEN_DEBUG off."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", STRONG_SECRET)
    monkeypatch.setenv("RESET_TOKEN_DEBUG", "false")

    import config

    config.get_settings.cache_clear()

    from fastapi.testclient import TestClient

    import main
    from database import get_supabase

    # Rate limiter would block repeated calls in a tight test loop.
    if hasattr(main.app.state, "limiter"):
        main.app.state.limiter.enabled = False

    yield main, TestClient, get_supabase

    main.app.dependency_overrides.pop(get_supabase, None)


def _override_user(main, get_supabase, user_row):
    main.app.dependency_overrides[get_supabase] = lambda: _FakeClient(user_row)


def test_request_reset_existing_email_has_no_token_in_body(reset_client):
    main, TestClient, get_supabase = reset_client
    _override_user(main, get_supabase, {"id": "user-1", "email": "known@harven.ai"})
    client = TestClient(main.app)
    resp = client.post("/auth/request-reset", json={"email": "known@harven.ai"})
    assert resp.status_code == 200
    assert "token" not in resp.json()


def test_request_reset_identical_body_for_known_and_unknown(reset_client):
    main, TestClient, get_supabase = reset_client
    client = TestClient(main.app)

    _override_user(main, get_supabase, {"id": "user-1", "email": "known@harven.ai"})
    known = client.post("/auth/request-reset", json={"email": "known@harven.ai"})

    _override_user(main, get_supabase, None)
    unknown = client.post("/auth/request-reset", json={"email": "nobody@harven.ai"})

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert "token" not in known.json() and "token" not in unknown.json()


def test_request_reset_does_not_log_token(reset_client, caplog):
    main, TestClient, get_supabase = reset_client
    _override_user(main, get_supabase, {"id": "user-1", "email": "known@harven.ai"})
    client = TestClient(main.app)
    with caplog.at_level(logging.INFO, logger="harven"):
        client.post("/auth/request-reset", json={"email": "known@harven.ai"})

    # The token is a uuid4; it must never appear in any log record.
    joined = " ".join(r.getMessage() for r in caplog.records)
    # A generated reset event may be logged by user-id, but never with a uuid token.
    import re

    assert not re.search(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", joined
    ), f"reset token leaked into logs: {joined}"
