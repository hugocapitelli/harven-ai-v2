"""User repository — Supabase client API."""
from typing import Optional, Dict, List, Tuple
from supabase import Client
from .base import BaseRepository


class UserRepository(BaseRepository):
    def __init__(self, client: Client):
        super().__init__(client, "users")

    def get_by_ra(self, ra: str) -> Optional[Dict]:
        res = self.client.table(self.table).select("*").eq("ra", ra).maybe_single().execute()
        return res.data if res else None

    def search(self, query_str: str, role: str = None, skip: int = 0, limit: int = 20) -> Tuple[List[Dict], int]:
        q = self.client.table(self.table).select("*", count="exact")
        q = q.or_(f"name.ilike.%{query_str}%,email.ilike.%{query_str}%,ra.ilike.%{query_str}%")
        if role:
            q = q.eq("role", role)
        q = q.order("name").range(skip, skip + limit - 1)
        res = q.execute()
        return res.data or [], res.count or 0
