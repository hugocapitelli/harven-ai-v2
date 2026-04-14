"""Gamification repository — Supabase client API."""
from typing import Dict, List, Optional, Tuple
from supabase import Client


class GamificationRepository:
    def __init__(self, client: Client):
        self.client = client

    # ── Stats ────────────────────────────────────────────

    def get_user_stats(self, user_id: str) -> Dict:
        res = (
            self.client.table("user_stats")
            .select("*")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if res.data:
            return res.data
        # Auto-create stats row
        new_stats = {"user_id": user_id, "total_points": 0}
        create_res = self.client.table("user_stats").insert(new_stats).execute()
        return create_res.data[0] if create_res.data else new_stats

    # ── Activities ───────────────────────────────────────

    def get_user_activities(self, user_id: str, skip: int = 0, limit: int = 50) -> Tuple[List[Dict], int]:
        q = (
            self.client.table("user_activities")
            .select("*", count="exact")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .range(skip, skip + limit - 1)
        )
        res = q.execute()
        return res.data or [], res.count or 0

    def add_activity(self, user_id: str, data: dict) -> Dict:
        data["user_id"] = user_id
        res = self.client.table("user_activities").insert(data).execute()
        return res.data[0] if res.data else {}

    # ── Achievements ─────────────────────────────────────

    def get_achievements(self, user_id: str) -> List[Dict]:
        res = (
            self.client.table("user_achievements")
            .select("*")
            .eq("user_id", user_id)
            .order("unlocked_at", desc=True)
            .execute()
        )
        return res.data or []

    def get_achievement(self, user_id: str, achievement_id: str) -> Optional[Dict]:
        res = (
            self.client.table("user_achievements")
            .select("*")
            .eq("user_id", user_id)
            .eq("id", achievement_id)
            .maybe_single()
            .execute()
        )
        return res.data

    def unlock_achievement(self, data: dict) -> Dict:
        res = self.client.table("user_achievements").insert(data).execute()
        return res.data[0] if res.data else {}

    # ── Certificates ─────────────────────────────────────

    def get_certificates(self, user_id: str) -> List[Dict]:
        res = (
            self.client.table("certificates")
            .select("*")
            .eq("user_id", user_id)
            .order("issued_at", desc=True)
            .execute()
        )
        return res.data or []

    def get_certificate(self, user_id: str, course_id: str) -> Optional[Dict]:
        res = (
            self.client.table("certificates")
            .select("*")
            .eq("user_id", user_id)
            .eq("course_id", course_id)
            .maybe_single()
            .execute()
        )
        return res.data

    def issue_certificate(self, data: dict) -> Dict:
        res = self.client.table("certificates").insert(data).execute()
        return res.data[0] if res.data else {}

    # ── Progress ─────────────────────────────────────────

    def get_course_progress(self, user_id: str, course_id: str) -> Optional[Dict]:
        res = (
            self.client.table("course_progress")
            .select("*")
            .eq("user_id", user_id)
            .eq("course_id", course_id)
            .maybe_single()
            .execute()
        )
        return res.data

    def upsert_progress(self, data: dict) -> Dict:
        res = self.client.table("course_progress").upsert(data).execute()
        return res.data[0] if res.data else {}
