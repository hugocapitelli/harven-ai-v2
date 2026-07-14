"""Regression — ``.maybe_single().execute()`` returns ``None`` on ZERO rows.

Production bug (HTTP 500 on ``POST /api/ai/audio/generate-from-content``):
``supabase-py``/``postgrest`` 2.28.x return ``None`` (the whole response object,
NOT a response with ``data=None``) from ``.maybe_single().execute()`` when no
row matches. ``BaseRepository.get_by_id`` accessed ``res.data`` unconditionally,
so any lookup of a not-yet-existing id (e.g. the freshly minted ``job_id`` that
``TtsJobRepository.seed_processing`` checks for idempotency) raised
``AttributeError: 'NoneType' object has no attribute 'data'`` -> 500.

The in-memory ``FakeSupabaseClient`` returned a faithful-looking ``_Result(
data=None)`` on zero rows, so the existing suites could NOT reproduce this — the
regression here uses a stub that mirrors the REAL library behaviour (``execute``
-> ``None``) to lock the contract at the unit level.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from repositories.base import BaseRepository
from repositories.tts_job_repo import TtsJobRepository


class _NoneOnZeroRowQuery:
    """Minimal query builder mirroring supabase-py 2.28.x semantics:

    ``.maybe_single().execute()`` returns ``None`` when nothing matches; a plain
    ``.execute()`` returns an object with ``.data``/``.count``.
    """

    def __init__(self, table_rows: List[Dict[str, Any]], store: Dict[str, List[Dict[str, Any]]], table: str):
        self._rows = table_rows
        self._store = store
        self._table = table
        self._filters: List[tuple] = []
        self._maybe_single = False
        self._op = "select"
        self._payload: Any = None

    def select(self, *a, **k):
        self._op = "select"
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def eq(self, col, val):
        self._filters.append((col, val))
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def maybe_single(self):
        self._maybe_single = True
        return self

    def _matches(self, row):
        return all(str(row.get(c)) == str(v) for c, v in self._filters)

    def execute(self):
        if self._op == "insert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            for p in payloads:
                self._rows.append(dict(p))
            return type("_R", (), {"data": [dict(p) for p in payloads], "count": None})()
        matched = [r for r in self._rows if self._matches(r)]
        if self._maybe_single:
            # THE production behaviour: None (not a response) when zero rows.
            if not matched:
                return None
            return type("_R", (), {"data": matched[0], "count": None})()
        return type("_R", (), {"data": matched, "count": None})()


class _NoneOnZeroRowClient:
    def __init__(self):
        self._store: Dict[str, List[Dict[str, Any]]] = {}

    def table(self, name):
        return _NoneOnZeroRowQuery(self._store.setdefault(name, []), self._store, name)


def test_get_by_id_missing_row_returns_none_not_raise():
    """A missing id must yield ``None`` (the declared ``Optional[Dict]`` contract),
    never ``AttributeError`` -> 500."""
    repo = BaseRepository(_NoneOnZeroRowClient(), "anything")
    assert repo.get_by_id("does-not-exist") is None


def test_seed_processing_does_not_500_on_fresh_job_id():
    """Reproduces the production path: ``seed_processing`` checks ``get_by_id`` for
    a brand-new ``job_id`` (guaranteed zero rows) BEFORE inserting."""
    repo = TtsJobRepository(_NoneOnZeroRowClient())
    job = repo.seed_processing("brand-new-job", "content-x", "user-x", "summary")
    assert job["id"] == "brand-new-job"
    assert job["status"] == "processing"
