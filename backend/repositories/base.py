"""Base repository using Supabase client API."""
from typing import Any, Dict, List, Optional
from supabase import Client


class BaseRepository:
    """Generic CRUD via Supabase PostgREST API."""

    def __init__(self, client: Client, table_name: str):
        self.client = client
        self.table = table_name

    # ── READ ─────────────────────────────────────────────
    def get_by_id(self, id: str) -> Optional[Dict]:
        res = self.client.table(self.table).select("*").eq("id", id).maybe_single().execute()
        return res.data

    def get_all(
        self,
        filters: Optional[Dict[str, Any]] = None,
        order_by: str = "created_at",
        desc: bool = True,
        limit: int = 100,
        offset: int = 0,
        select: str = "*",
    ) -> tuple[List[Dict], int]:
        q = self.client.table(self.table).select(select, count="exact")
        if filters:
            for key, value in filters.items():
                if isinstance(value, list):
                    q = q.in_(key, value)
                else:
                    q = q.eq(key, value)
        q = q.order(order_by, desc=desc).range(offset, offset + limit - 1)
        res = q.execute()
        return res.data or [], res.count or 0

    def get_one(self, filters: Dict[str, Any]) -> Optional[Dict]:
        q = self.client.table(self.table).select("*")
        for key, value in filters.items():
            q = q.eq(key, value)
        res = q.maybe_single().execute()
        return res.data

    # ── CREATE ───────────────────────────────────────────
    def create(self, data: Dict[str, Any]) -> Dict:
        res = self.client.table(self.table).insert(data).execute()
        return res.data[0] if res.data else {}

    def create_many(self, data_list: List[Dict[str, Any]]) -> List[Dict]:
        res = self.client.table(self.table).insert(data_list).execute()
        return res.data or []

    # ── UPDATE ───────────────────────────────────────────
    def update(self, id: str, data: Dict[str, Any]) -> Optional[Dict]:
        res = self.client.table(self.table).update(data).eq("id", id).execute()
        return res.data[0] if res.data else None

    def update_where(self, filters: Dict[str, Any], data: Dict[str, Any]) -> List[Dict]:
        q = self.client.table(self.table).update(data)
        for key, value in filters.items():
            q = q.eq(key, value)
        res = q.execute()
        return res.data or []

    # ── DELETE ───────────────────────────────────────────
    def delete(self, id: str) -> bool:
        res = self.client.table(self.table).delete().eq("id", id).execute()
        return bool(res.data)

    def delete_where(self, filters: Dict[str, Any]) -> int:
        q = self.client.table(self.table).delete()
        for key, value in filters.items():
            q = q.eq(key, value)
        res = q.execute()
        return len(res.data) if res.data else 0

    # ── UPSERT ───────────────────────────────────────────
    def upsert(self, data: Dict[str, Any]) -> Dict:
        res = self.client.table(self.table).upsert(data).execute()
        return res.data[0] if res.data else {}

    # ── SEARCH ───────────────────────────────────────────
    def search(self, column: str, query: str, limit: int = 20) -> List[Dict]:
        res = self.client.table(self.table).select("*").ilike(column, f"%{query}%").limit(limit).execute()
        return res.data or []
