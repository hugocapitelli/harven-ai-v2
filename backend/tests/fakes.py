"""In-memory fake of the Supabase client for the Harven security test suite.

This is a duck-typed double of ``supabase.Client`` that stores tables as lists of
dict rows in memory and exposes the same fluent builder the production code uses:

    client.table(name).select(...).eq(col, val).maybe_single().execute()
    client.table(name).insert({...}).execute()
    client.table(name).update({...}).eq(col, val).execute()
    client.table(name).delete().eq(col, val).execute()

``.execute()`` returns a ``SimpleNamespace`` with a ``.data`` attribute (a list,
a single row, or ``None``) plus a ``.count`` attribute, matching what
``main.py`` / ``routes_ai.py`` / ``routes_admin.py`` consume.

No network, no real DB: every test runs fully in-process. Chains that the
production code does not use raise ``NotImplementedError`` rather than silently
returning empty data, so a missing capability surfaces as a loud failure instead
of masking an IDOR gap.

Mutation auditing
-----------------
Every write the fake applies is appended to ``client.mutations`` as a record
``{"table", "op", "rows", "filters"}``. The IDOR helpers use this log to assert
that a forbidden cross-actor request produced **no** mutation against another
user's row.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any, Dict, List, Optional


class _Result(SimpleNamespace):
    """``.execute()`` return value — has ``.data`` and ``.count``."""

    def __init__(self, data: Any = None, count: Optional[int] = None):
        super().__init__(data=data, count=count)


class _QueryBuilder:
    """Accumulates filters/op and resolves them against an in-memory table.

    Supports the read chain (``select``/``eq``/``order``/``limit``/``single``/
    ``maybe_single``) and the write chains (``insert``/``update``/``delete``).
    """

    def __init__(self, fake: "FakeSupabaseClient", table: str):
        self._fake = fake
        self._table = table
        self._op = "select"          # select | insert | update | delete
        self._filters: List[tuple] = []  # list of (col, value) for .eq
        self._payload: Any = None        # insert/update payload
        self._single = False             # .single() -> dict or raise
        self._maybe_single = False       # .maybe_single() -> dict or None
        self._count_mode: Optional[str] = None
        self._limit: Optional[int] = None
        self._order: Optional[str] = None
        # Accumulated (column, descending) sort keys, applied left-to-right so a
        # chained ``.order("created_at").order("sequence").order("id")`` produces a
        # stable multi-key sort (mirrors PostgREST). ``_order`` is kept for
        # backwards-compat (last single key) but ``_orders`` drives resolution.
        self._orders: List[tuple] = []

    # ── read shaping ────────────────────────────────────────────────
    def select(self, *_args, **kwargs) -> "_QueryBuilder":
        self._op = "select"
        if "count" in kwargs:
            self._count_mode = kwargs["count"]
        return self

    def eq(self, col: str, value: Any) -> "_QueryBuilder":
        self._filters.append((col, value))
        return self

    def order(self, col: str, *_a, **kwargs) -> "_QueryBuilder":
        self._order = col
        self._orders.append((col, bool(kwargs.get("desc", False))))
        return self

    def limit(self, n: int) -> "_QueryBuilder":
        self._limit = n
        return self

    def single(self) -> "_QueryBuilder":
        self._single = True
        return self

    def maybe_single(self) -> "_QueryBuilder":
        self._maybe_single = True
        return self

    # ── write shaping ───────────────────────────────────────────────
    def insert(self, payload: Any) -> "_QueryBuilder":
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload: Dict[str, Any]) -> "_QueryBuilder":
        self._op = "update"
        self._payload = payload
        return self

    def delete(self) -> "_QueryBuilder":
        self._op = "delete"
        return self

    # ── resolution ──────────────────────────────────────────────────
    def _matches(self, row: Dict[str, Any]) -> bool:
        return all(str(row.get(c)) == str(v) for c, v in self._filters)

    def execute(self) -> _Result:
        rows = self._fake._tables.setdefault(self._table, [])

        if self._op == "select":
            matched = [copy.deepcopy(r) for r in rows if self._matches(r)]
            # Apply accumulated sort keys right-to-left (stable sort) so the first
            # ``.order`` is the most significant key — matching PostgREST chaining.
            if self._orders:
                for col, desc in reversed(self._orders):
                    matched.sort(
                        key=lambda r, c=col: (r.get(c) is None, r.get(c)),
                        reverse=desc,
                    )
            elif self._order:
                matched.sort(key=lambda r: (r.get(self._order) is None, r.get(self._order)))
            if self._limit is not None:
                matched = matched[: self._limit]
            count = len(matched) if self._count_mode else None
            if self._single:
                if not matched:
                    # supabase-py raises on .single() with no row; mirror "empty".
                    return _Result(data=None, count=count)
                return _Result(data=matched[0], count=count)
            if self._maybe_single:
                return _Result(data=(matched[0] if matched else None), count=count)
            return _Result(data=matched, count=count)

        if self._op == "insert":
            payloads = self._payload if isinstance(self._payload, list) else [self._payload]
            inserted = []
            for p in payloads:
                row = copy.deepcopy(p)
                row.setdefault("id", self._fake._next_id(self._table))
                rows.append(row)
                inserted.append(copy.deepcopy(row))
            self._fake._record_mutation(self._table, "insert", inserted, self._filters)
            return _Result(data=inserted)

        if self._op == "update":
            updated = []
            for r in rows:
                if self._matches(r):
                    r.update(self._payload)
                    updated.append(copy.deepcopy(r))
            self._fake._record_mutation(self._table, "update", updated, self._filters)
            return _Result(data=updated)

        if self._op == "delete":
            kept, removed = [], []
            for r in rows:
                (removed if self._matches(r) else kept).append(r)
            self._fake._tables[self._table] = kept
            self._fake._record_mutation(self._table, "delete", [copy.deepcopy(r) for r in removed], self._filters)
            return _Result(data=[copy.deepcopy(r) for r in removed])

        raise NotImplementedError(f"FakeSupabaseClient: unsupported op {self._op!r}")


class _RpcBuilder:
    """Deferred RPC call — ``client.rpc(name, params).execute()`` returns a result
    whose ``.data`` is the RPC's return value (matching supabase-py's shape)."""

    def __init__(self, fake: "FakeSupabaseClient", name: str, params: Dict[str, Any]):
        self._fake = fake
        self._name = name
        self._params = params

    def execute(self) -> _Result:
        data = self._fake._run_rpc(self._name, self._params)
        return _Result(data=data)


class FakeSupabaseClient:
    """In-memory stand-in for ``supabase.Client``.

    Seed tables with :meth:`seed` (replaces a table) or :meth:`add` (appends a
    row). Inspect applied writes via :attr:`mutations`.
    """

    def __init__(
        self,
        tables: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        rpc_enabled: bool = False,
    ):
        self._tables: Dict[str, List[Dict[str, Any]]] = {}
        self._id_counters: Dict[str, int] = {}
        self.mutations: List[Dict[str, Any]] = []
        # When False, this fake exposes NO ``.rpc`` attribute at all — mirroring a
        # DB where migration B (TPP-1) has not been applied, so chat_repo exercises
        # its non-RPC fallback. When True, ``.rpc`` implements the two TPP-1 RPCs
        # (``increment_chat_session_messages`` / ``upsert_chat_session``) atomically
        # against the in-memory tables so the RPC path can be tested directly.
        self._rpc_enabled = rpc_enabled
        self.rpc_calls: List[Dict[str, Any]] = []
        # ``rpc`` is bound as an INSTANCE attribute only when enabled, so a disabled
        # fake has no ``rpc`` attribute at all: ``getattr(client, "rpc", None)`` is
        # None and chat_repo takes its non-RPC fallback (mirrors an un-migrated DB).
        if rpc_enabled:
            self.rpc = self._rpc_entry  # type: ignore[assignment]
        if tables:
            for name, rows in tables.items():
                self.seed(name, rows)

    # ── builder entry point ─────────────────────────────────────────
    def table(self, name: str) -> _QueryBuilder:
        return _QueryBuilder(self, name)

    # ── RPC (only bound onto the instance when rpc_enabled=True) ─────
    def _rpc_entry(self, name: str, params: Optional[Dict[str, Any]] = None) -> "_RpcBuilder":
        """Stand-in for ``client.rpc(name, params)`` (chained ``.execute()``).

        Implements the two RPCs the chat layer relies on, atomically against the
        in-memory tables.
        """
        return _RpcBuilder(self, name, params or {})

    def _run_rpc(self, name: str, params: Dict[str, Any]) -> Any:
        self.rpc_calls.append({"name": name, "params": dict(params)})
        if name == "increment_chat_session_messages":
            sid = params.get("p_session_id")
            for r in self._tables.setdefault("chat_sessions", []):
                if str(r.get("id")) == str(sid):
                    r["total_messages"] = (r.get("total_messages") or 0) + 1
                    self._record_mutation("chat_sessions", "update", [copy.deepcopy(r)], [("id", sid)])
                    return r["total_messages"]
            return None
        if name == "upsert_chat_session":
            uid = params.get("p_user_id")
            cid = params.get("p_content_id")
            rows = self._tables.setdefault("chat_sessions", [])
            for r in rows:
                if str(r.get("user_id")) == str(uid) and str(r.get("content_id")) == str(cid):
                    return copy.deepcopy(r)
            row = {
                "id": self._next_id("chat_sessions"),
                "user_id": uid,
                "content_id": cid,
                "status": "active",
                "total_messages": 0,
            }
            rows.append(row)
            self._record_mutation("chat_sessions", "insert", [copy.deepcopy(row)], [])
            return copy.deepcopy(row)
        if name == "increment_token_usage":
            # TKN-1's atomic upsert: one row per (user_id, usage_date); the daily
            # counter is summed in-DB and the new total returned (mirrors
            # INSERT ... ON CONFLICT DO UPDATE SET tokens_used = tokens_used +
            # EXCLUDED.tokens_used RETURNING tokens_used).
            uid = params.get("p_user_id")
            udate = params.get("p_usage_date")
            delta = params.get("p_tokens") or 0
            rows = self._tables.setdefault("token_usage", [])
            for r in rows:
                if str(r.get("user_id")) == str(uid) and str(r.get("usage_date")) == str(udate):
                    r["tokens_used"] = (r.get("tokens_used") or 0) + delta
                    self._record_mutation(
                        "token_usage", "update", [copy.deepcopy(r)],
                        [("user_id", uid), ("usage_date", udate)],
                    )
                    return r["tokens_used"]
            row = {
                "id": self._next_id("token_usage"),
                "user_id": uid,
                "usage_date": udate,
                "tokens_used": delta,
            }
            rows.append(row)
            self._record_mutation("token_usage", "insert", [copy.deepcopy(row)], [])
            return row["tokens_used"]
        raise NotImplementedError(f"FakeSupabaseClient: unknown rpc {name!r}")

    # ── seeding / inspection ────────────────────────────────────────
    def seed(self, table: str, rows: List[Dict[str, Any]]) -> "FakeSupabaseClient":
        self._tables[table] = [copy.deepcopy(r) for r in rows]
        return self

    def add(self, table: str, row: Dict[str, Any]) -> "FakeSupabaseClient":
        self._tables.setdefault(table, []).append(copy.deepcopy(row))
        return self

    def rows(self, table: str) -> List[Dict[str, Any]]:
        return [copy.deepcopy(r) for r in self._tables.get(table, [])]

    def find(self, table: str, **filters) -> Optional[Dict[str, Any]]:
        for r in self._tables.get(table, []):
            if all(str(r.get(c)) == str(v) for c, v in filters.items()):
                return copy.deepcopy(r)
        return None

    # ── internals ───────────────────────────────────────────────────
    def _next_id(self, table: str) -> str:
        self._id_counters[table] = self._id_counters.get(table, 0) + 1
        return f"{table}-auto-{self._id_counters[table]}"

    def _record_mutation(self, table: str, op: str, rows: List[Dict[str, Any]], filters: List[tuple]) -> None:
        self.mutations.append({
            "table": table,
            "op": op,
            "rows": rows,
            "filters": list(filters),
        })

    def reset_mutations(self) -> None:
        self.mutations.clear()


# ===========================================================================
# ASYNC-AI-3 — OpenAI test doubles (async + sync) for the concurrency suite
# ===========================================================================
# These fakes let the async LLM tests run fully headless: no OPENAI_API_KEY, no
# network. They mirror exactly the response shape the production code reads:
#
#   _call_openai (ai_service.py):  resp.choices[0].message.content,
#                                  resp.usage.{prompt,completion,total}_tokens,
#                                  resp.model
#   _run_tts_job (routes_ai.py):   resp.choices[0].message.content
#   ai_transcribe (routes_ai.py):  resp.text
#
# The async client's ``chat.completions.create`` is a coroutine that can sleep a
# configurable ``delay`` — this is the lever the concurrency oracle uses: with a
# real synchronous client (pre-fix) N awaited calls serialize; with this async
# fake (post-fix) they overlap under ``asyncio.gather``.

import asyncio
import time as _time


class _FakeMessage(SimpleNamespace):
    def __init__(self, content: str):
        super().__init__(content=content)


class _FakeChoice(SimpleNamespace):
    def __init__(self, content: str):
        super().__init__(message=_FakeMessage(content))


class _FakeUsage(SimpleNamespace):
    def __init__(self, prompt: int = 10, completion: int = 20):
        super().__init__(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
        )


class _FakeChatCompletion(SimpleNamespace):
    def __init__(self, content: str, model: str = "fake-model"):
        super().__init__(
            choices=[_FakeChoice(content)],
            usage=_FakeUsage(),
            model=model,
        )


class _FakeTranscription(SimpleNamespace):
    def __init__(self, text: str):
        super().__init__(text=text)


class _AsyncCompletions:
    def __init__(self, parent: "FakeAsyncOpenAI"):
        self._parent = parent

    async def create(self, **kwargs) -> _FakeChatCompletion:
        p = self._parent
        p.calls.append(kwargs)
        if p.delay:
            # The crux of the concurrency oracle: a real async client yields the
            # loop here so other awaited calls progress concurrently.
            await asyncio.sleep(p.delay)
        if p.raise_exc is not None:
            raise p.raise_exc
        return _FakeChatCompletion(p.response_text, model=p.model)


class _AsyncTranscriptions:
    def __init__(self, parent: "FakeAsyncOpenAI"):
        self._parent = parent

    async def create(self, **kwargs) -> _FakeTranscription:
        p = self._parent
        p.transcribe_calls.append(kwargs)
        if p.delay:
            await asyncio.sleep(p.delay)
        if p.raise_exc is not None:
            raise p.raise_exc
        return _FakeTranscription(p.transcribe_text)


class FakeAsyncOpenAI:
    """Async stand-in for ``openai.AsyncOpenAI`` — no network.

    Mirrors the surface used by the code under test:
      * ``client.chat.completions.create(**kwargs)`` -> awaitable chat completion
      * ``client.audio.transcriptions.create(**kwargs)`` -> awaitable transcription

    Configurable:
      * ``delay``          — per-call ``asyncio.sleep`` (simulated LLM latency)
      * ``response_text``  — chat completion content
      * ``transcribe_text``— whisper text
      * ``raise_exc``      — raise instead of returning (timeout/error mapping)

    Inspectable:
      * ``calls``            — list of chat ``create`` kwargs
      * ``transcribe_calls`` — list of transcribe ``create`` kwargs
    """

    def __init__(
        self,
        delay: float = 0.0,
        response_text: str = '{"questions": []}',
        transcribe_text: str = "transcribed text",
        model: str = "fake-model",
        raise_exc: Optional[BaseException] = None,
    ):
        self.delay = delay
        self.response_text = response_text
        self.transcribe_text = transcribe_text
        self.model = model
        self.raise_exc = raise_exc
        self.calls: List[Dict[str, Any]] = []
        self.transcribe_calls: List[Dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=_AsyncCompletions(self))
        self.audio = SimpleNamespace(transcriptions=_AsyncTranscriptions(self))


class _SyncCompletions:
    def __init__(self, parent: "FakeSyncOpenAI"):
        self._parent = parent

    def create(self, **kwargs) -> _FakeChatCompletion:
        p = self._parent
        p.calls.append(kwargs)
        if p.delay:
            # Deliberately a BLOCKING sleep: this is the off-event-loop client used by
            # the TTS background thread. It must never be awaited.
            _time.sleep(p.delay)
        if p.raise_exc is not None:
            raise p.raise_exc
        return _FakeChatCompletion(p.response_text, model=p.model)


class FakeSyncOpenAI:
    """Synchronous stand-in for ``openai.OpenAI`` — used by the TTS thread path.

    Only exposes ``chat.completions.create`` (blocking), matching ``_run_tts_job``'s
    use of ``svc.sync_client``. Calling this is correct OFF the event loop; the test
    asserts the thread reaches 'done' without any await/coroutine error.
    """

    def __init__(
        self,
        delay: float = 0.0,
        response_text: str = "summarized content",
        model: str = "fake-model",
        raise_exc: Optional[BaseException] = None,
    ):
        self.delay = delay
        self.response_text = response_text
        self.model = model
        self.raise_exc = raise_exc
        self.calls: List[Dict[str, Any]] = []
        self.chat = SimpleNamespace(completions=_SyncCompletions(self))
