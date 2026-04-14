"""Notification repository — Supabase client API."""
from typing import Dict, List, Tuple
from supabase import Client
from .base import BaseRepository


class NotificationRepository(BaseRepository):
    def __init__(self, client: Client):
        super().__init__(client, "notifications")

    def get_by_user(self, user_id: str, skip: int = 0, limit: int = 50) -> Tuple[List[Dict], int]:
        q = (
            self.client.table(self.table)
            .select("*", count="exact")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .range(skip, skip + limit - 1)
        )
        res = q.execute()
        return res.data or [], res.count or 0

    def count_unread(self, user_id: str) -> int:
        res = (
            self.client.table(self.table)
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("is_read", False)
            .execute()
        )
        return res.count or 0

    def mark_read(self, notification_id: str) -> None:
        self.client.table(self.table).update({"is_read": True}).eq("id", notification_id).execute()

    def mark_all_read(self, user_id: str) -> int:
        res = (
            self.client.table(self.table)
            .update({"is_read": True})
            .eq("user_id", user_id)
            .eq("is_read", False)
            .execute()
        )
        return len(res.data) if res.data else 0
