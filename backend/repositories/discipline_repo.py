"""Discipline repository — Supabase client API."""
from typing import Dict, List, Optional
from supabase import Client
from .base import BaseRepository


class DisciplineRepository(BaseRepository):
    def __init__(self, client: Client):
        super().__init__(client, "disciplines")

    # ── Teachers ────────────────────────────────────────
    def add_teacher(self, discipline_id: str, teacher_id: str) -> Dict:
        res = self.client.table("discipline_teachers").insert({
            "discipline_id": discipline_id,
            "teacher_id": teacher_id,
        }).execute()
        return res.data[0] if res.data else {}

    def remove_teacher(self, discipline_id: str, teacher_id: str) -> int:
        res = (
            self.client.table("discipline_teachers")
            .delete()
            .eq("discipline_id", discipline_id)
            .eq("teacher_id", teacher_id)
            .execute()
        )
        return len(res.data) if res.data else 0

    def get_teachers(self, discipline_id: str) -> List[Dict]:
        """Get teachers for a discipline with user details."""
        res = (
            self.client.table("discipline_teachers")
            .select("*, teacher:users!teacher_id(*)")
            .eq("discipline_id", discipline_id)
            .execute()
        )
        return res.data or []

    def get_teacher_discipline_ids(self, teacher_id: str) -> List[str]:
        """Get discipline IDs for a teacher."""
        res = (
            self.client.table("discipline_teachers")
            .select("discipline_id")
            .eq("teacher_id", teacher_id)
            .execute()
        )
        return [r["discipline_id"] for r in (res.data or [])]

    # ── Students ────────────────────────────────────────
    def add_student(self, discipline_id: str, student_id: str) -> Dict:
        res = self.client.table("discipline_students").insert({
            "discipline_id": discipline_id,
            "student_id": student_id,
        }).execute()
        return res.data[0] if res.data else {}

    def remove_student(self, discipline_id: str, student_id: str) -> int:
        res = (
            self.client.table("discipline_students")
            .delete()
            .eq("discipline_id", discipline_id)
            .eq("student_id", student_id)
            .execute()
        )
        return len(res.data) if res.data else 0

    def add_students_batch(self, discipline_id: str, student_ids: list) -> List[Dict]:
        data = [{"discipline_id": discipline_id, "student_id": sid} for sid in student_ids]
        res = self.client.table("discipline_students").insert(data).execute()
        return res.data or []

    def get_students(self, discipline_id: str) -> List[Dict]:
        """Get students for a discipline with user details."""
        res = (
            self.client.table("discipline_students")
            .select("*, student:users!student_id(*)")
            .eq("discipline_id", discipline_id)
            .execute()
        )
        return res.data or []

    def get_student_discipline_ids(self, student_id: str) -> List[str]:
        """Get discipline IDs for a student."""
        res = (
            self.client.table("discipline_students")
            .select("discipline_id")
            .eq("student_id", student_id)
            .execute()
        )
        return [r["discipline_id"] for r in (res.data or [])]
