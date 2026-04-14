"""Content repository — Supabase client API."""
from typing import Dict, List
from supabase import Client
from .base import BaseRepository


class ContentRepository(BaseRepository):
    def __init__(self, client: Client):
        super().__init__(client, "contents")

    def get_by_chapter(self, chapter_id: str) -> List[Dict]:
        res = (
            self.client.table(self.table)
            .select("*")
            .eq("chapter_id", chapter_id)
            .order("order")
            .execute()
        )
        return res.data or []
