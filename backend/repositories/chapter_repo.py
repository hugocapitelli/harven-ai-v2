"""Chapter repository — Supabase client API."""
from typing import Dict, List
from supabase import Client
from .base import BaseRepository


class ChapterRepository(BaseRepository):
    def __init__(self, client: Client):
        super().__init__(client, "chapters")

    def get_by_course(self, course_id: str) -> List[Dict]:
        res = (
            self.client.table(self.table)
            .select("*")
            .eq("course_id", course_id)
            .order("order")
            .execute()
        )
        return res.data or []
