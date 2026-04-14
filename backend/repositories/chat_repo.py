"""Chat repository — Supabase client API."""
from typing import Dict, List, Optional
from supabase import Client
from .base import BaseRepository


class ChatRepository(BaseRepository):
    def __init__(self, client: Client):
        super().__init__(client, "chat_sessions")

    def get_user_sessions(self, user_id: str) -> List[Dict]:
        res = (
            self.client.table(self.table)
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        sessions = res.data or []
        for session in sessions:
            msgs_res = (
                self.client.table("chat_messages")
                .select("*")
                .eq("session_id", session["id"])
                .order("created_at")
                .execute()
            )
            session["messages"] = msgs_res.data or []
        return sessions

    def get_by_content_user(self, content_id: str, user_id: str) -> Optional[Dict]:
        res = (
            self.client.table(self.table)
            .select("*")
            .eq("content_id", content_id)
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        return res.data

    def add_message(self, session_id: str, data: dict) -> Dict:
        data["session_id"] = session_id
        res = self.client.table("chat_messages").insert(data).execute()
        return res.data[0] if res.data else {}

    def get_session_messages(self, session_id: str) -> List[Dict]:
        res = (
            self.client.table("chat_messages")
            .select("*")
            .eq("session_id", session_id)
            .order("created_at")
            .execute()
        )
        return res.data or []

    def get_session_with_messages(self, session_id: str) -> Optional[Dict]:
        res = self.client.table(self.table).select("*").eq("id", session_id).maybe_single().execute()
        if not res.data:
            return None
        session = res.data
        session["messages"] = self.get_session_messages(session_id)
        return session
