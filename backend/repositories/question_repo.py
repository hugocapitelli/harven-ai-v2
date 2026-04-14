"""Question repository — Supabase client API."""
from typing import Dict, List
from supabase import Client
from .base import BaseRepository


class QuestionRepository(BaseRepository):
    def __init__(self, client: Client):
        super().__init__(client, "questions")

    def get_by_content(self, content_id: str) -> List[Dict]:
        res = (
            self.client.table(self.table)
            .select("*")
            .eq("content_id", content_id)
            .execute()
        )
        return res.data or []

    def batch_create(self, content_id: str, questions: list) -> List[Dict]:
        data = []
        for q in questions:
            q["content_id"] = content_id
            data.append(q)
        res = self.client.table(self.table).insert(data).execute()
        return res.data or []
