"""SEC-ROT-1 / SEC-ROT-2 / SEC-ROT-3 — DB-backed JWT secret + rotation.

Covers the three-story rotation chain:

* SEC-ROT-1: ``get_active_jwt_secret`` seeds from the bootstrap env on a NULL
  column, caches with a TTL, and is fail-closed (weak bootstrap → raise; DB
  error → strong-bootstrap fallback, never a default).
* SEC-ROT-2: ``create_access_token`` / ``get_current_user`` sign & verify from
  the provider; round-trip holds; a token signed under a different secret → 401.
* SEC-ROT-3: ``POST /admin/force-logout`` rotates the secret **in the DB** (no
  filesystem write), invalidates the cache, so a pre-rotation token → 401 and a
  post-rotation login → 200 without a restart.

The provider keeps a process-global cache, so each test invalidates it up-front
to stay isolated.
"""
from __future__ import annotations

import time

import pytest
from jose import jwt

import config
import jwt_secret_provider as provider
from conftest import (
    ADMIN_ID,
    SETTINGS_ID,
    STRONG_SECRET,
    STUDENT_A_ID,
    make_seed_tables,
)
from fakes import FakeSupabaseClient
from jwt_secret_provider import (
    WeakJWTSecretError,
    get_active_jwt_secret,
    invalidate_jwt_secret_cache,
)


@pytest.fixture(autouse=True)
def _isolate_provider_cache(monkeypatch):
    """Each test starts with a cleared provider cache and a strong bootstrap env."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("JWT_SECRET_KEY", STRONG_SECRET)
    config.get_settings.cache_clear()
    invalidate_jwt_secret_cache()
    yield
    invalidate_jwt_secret_cache()


def _fresh_fake() -> FakeSupabaseClient:
    return FakeSupabaseClient(make_seed_tables())


# ---------------------------------------------------------------------------
# SEC-ROT-1 — provider behaviour
# ---------------------------------------------------------------------------
def test_seed_on_null_persists_and_stamps_rotated_at():
    """NULL column → seed from bootstrap env, persist, stamp jwt_secret_rotated_at."""
    fake = _fresh_fake()
    assert fake.find("system_settings", id=SETTINGS_ID)["jwt_secret"] is None

    secret = get_active_jwt_secret(fake)

    assert secret == STRONG_SECRET
    row = fake.find("system_settings", id=SETTINGS_ID)
    assert row["jwt_secret"] == STRONG_SECRET
    assert row["jwt_secret_rotated_at"] is not None


def test_seed_creates_row_when_settings_absent():
    """No settings row at all → provider creates one and seeds it."""
    fake = FakeSupabaseClient({"system_settings": []})
    secret = get_active_jwt_secret(fake)
    assert secret == STRONG_SECRET
    rows = fake.rows("system_settings")
    assert len(rows) == 1
    assert rows[0]["jwt_secret"] == STRONG_SECRET


def test_cache_hit_within_ttl_does_not_query_db(monkeypatch):
    """A second call within the TTL uses the cache (no further DB read)."""
    fake = _fresh_fake()
    get_active_jwt_secret(fake)  # seeds + caches

    # Mutate the DB underneath; within TTL the cached value must still win.
    fake.table("system_settings").update({"jwt_secret": "y" * 48}).eq(
        "id", SETTINGS_ID
    ).execute()

    # Sanity: TTL is comfortably > the test's wall time.
    assert config.get_settings().JWT_SECRET_CACHE_TTL >= 1
    assert get_active_jwt_secret(fake) == STRONG_SECRET  # cached, not the new DB value


def test_cache_expiry_rereads_db(monkeypatch):
    """After the TTL the provider re-reads the (rotated) DB value."""
    monkeypatch.setenv("JWT_SECRET_CACHE_TTL", "0")
    config.get_settings.cache_clear()
    invalidate_jwt_secret_cache()

    fake = _fresh_fake()
    get_active_jwt_secret(fake)  # seeds STRONG_SECRET, caches with TTL=0

    rotated = "z" * 48
    fake.table("system_settings").update({"jwt_secret": rotated}).eq(
        "id", SETTINGS_ID
    ).execute()
    time.sleep(0.01)  # ensure monotonic clock advances past TTL=0

    assert get_active_jwt_secret(fake) == rotated


def test_db_error_falls_back_to_strong_bootstrap():
    """A DB read error falls back to the (strong) bootstrap env secret."""
    class _Boom(FakeSupabaseClient):
        def table(self, name):  # noqa: D401
            raise RuntimeError("db down")

    fake = _Boom({})
    assert get_active_jwt_secret(fake) == STRONG_SECRET


def test_db_error_with_weak_bootstrap_raises(monkeypatch):
    """DB error AND a weak bootstrap → raise, never return a default secret."""
    monkeypatch.setenv("JWT_SECRET_KEY", "change-me-in-production")
    config.get_settings.cache_clear()
    invalidate_jwt_secret_cache()

    class _Boom(FakeSupabaseClient):
        def table(self, name):
            raise RuntimeError("db down")

    with pytest.raises(WeakJWTSecretError):
        get_active_jwt_secret(_Boom({}))


def test_short_bootstrap_raises(monkeypatch):
    """A too-short bootstrap secret is rejected (fail-closed), not seeded."""
    monkeypatch.setenv("JWT_SECRET_KEY", "short")  # < 32 chars
    config.get_settings.cache_clear()
    invalidate_jwt_secret_cache()

    with pytest.raises(WeakJWTSecretError):
        get_active_jwt_secret(_fresh_fake())


# ---------------------------------------------------------------------------
# SEC-ROT-2 — sign/verify through the provider
# ---------------------------------------------------------------------------
def test_token_roundtrip_via_provider(monkeypatch):
    """A token signed by create_access_token verifies via get_current_user."""
    import auth
    from database import get_supabase as real_get_supabase  # noqa: F401

    fake = _fresh_fake()
    # auth.create_access_token signs using database.get_supabase() — patch it.
    monkeypatch.setattr(auth, "get_supabase", lambda: fake)

    token = auth.create_access_token(STUDENT_A_ID, "STUDENT")

    # The DB was seeded by the sign path; verify the decode side reads the same.
    active = get_active_jwt_secret(fake)
    decoded = jwt.decode(token, active, algorithms=[config.get_settings().JWT_ALGORITHM])
    assert decoded["sub"] == STUDENT_A_ID
    assert decoded["role"] == "STUDENT"


def test_token_signed_with_other_secret_is_rejected(monkeypatch):
    """A token signed under a divergent secret fails verification (401 path)."""
    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    import auth

    fake = _fresh_fake()
    get_active_jwt_secret(fake)  # seed the active secret = STRONG_SECRET

    forged = jwt.encode(
        {"sub": STUDENT_A_ID, "role": "STUDENT"},
        "d" * 48,  # different, strong-looking, but NOT the active secret
        algorithm=config.get_settings().JWT_ALGORITHM,
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=forged)

    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(credentials=creds, client=fake)
    assert exc.value.status_code == 401


# ---------------------------------------------------------------------------
# SEC-ROT-3 — force_logout rotates in the DB, invalidates pre-rotation tokens
# ---------------------------------------------------------------------------
def test_force_logout_rotates_db_secret_and_no_fs_write(monkeypatch, tmp_path):
    """force_logout updates system_settings.jwt_secret and writes no .env file."""
    import asyncio
    import routes_admin

    fake = _fresh_fake()
    seeded = get_active_jwt_secret(fake)  # establish a current secret in the DB

    admin = {"id": ADMIN_ID, "role": "ADMIN", "name": "Admin One"}

    # Fail loudly if any .env write is attempted.
    import builtins
    real_open = builtins.open

    def _guard_open(path, mode="r", *a, **k):
        if "w" in mode and str(path).endswith(".env"):
            raise AssertionError(f"force_logout wrote to .env at {path!r}")
        return real_open(path, mode, *a, **k)

    monkeypatch.setattr(builtins, "open", _guard_open)

    result = asyncio.run(routes_admin.force_logout(admin=admin, client=fake))

    assert "message" in result
    new_secret = fake.find("system_settings", id=SETTINGS_ID)["jwt_secret"]
    assert new_secret != seeded
    assert len(new_secret) >= config.MIN_JWT_SECRET_LENGTH
    # Audit log preserved (log_type="security").
    logs = fake.rows("system_logs")
    assert any(l.get("log_type") == "security" for l in logs)


def test_pre_rotation_token_rejected_post_rotation(monkeypatch):
    """Token issued before force_logout → 401 afterwards; new login → 200, no restart."""
    import asyncio

    from fastapi import HTTPException
    from fastapi.security import HTTPAuthorizationCredentials

    import auth
    import routes_admin

    fake = _fresh_fake()
    monkeypatch.setattr(auth, "get_supabase", lambda: fake)

    # 1) Issue a token under the current (seeded) secret and confirm it verifies.
    old_token = auth.create_access_token(STUDENT_A_ID, "STUDENT")
    creds_old = HTTPAuthorizationCredentials(scheme="Bearer", credentials=old_token)
    user = auth.get_current_user(credentials=creds_old, client=fake)
    assert user["id"] == STUDENT_A_ID

    # 2) Admin force-logout rotates the DB secret + invalidates the cache.
    admin = {"id": ADMIN_ID, "role": "ADMIN", "name": "Admin One"}
    asyncio.run(routes_admin.force_logout(admin=admin, client=fake))

    # 3) The pre-rotation token now fails verification (no restart).
    with pytest.raises(HTTPException) as exc:
        auth.get_current_user(credentials=creds_old, client=fake)
    assert exc.value.status_code == 401

    # 4) A login AFTER the rotation issues a token that verifies (200).
    new_token = auth.create_access_token(STUDENT_A_ID, "STUDENT")
    creds_new = HTTPAuthorizationCredentials(scheme="Bearer", credentials=new_token)
    user2 = auth.get_current_user(credentials=creds_new, client=fake)
    assert user2["id"] == STUDENT_A_ID
