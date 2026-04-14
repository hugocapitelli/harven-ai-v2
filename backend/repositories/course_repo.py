"""Course repository — Supabase client API."""
from typing import Dict, List, Optional
from supabase import Client
from .base import BaseRepository


class CourseRepository(BaseRepository):
    def __init__(self, client: Client):
        super().__init__(client, "courses")

    def get_with_chapters(self, course_id: str) -> Optional[Dict]:
        """Get course with its chapters."""
        res = self.client.table(self.table).select("*").eq("id", course_id).maybe_single().execute()
        if not res.data:
            return None
        course = res.data
        chapters_res = (
            self.client.table("chapters")
            .select("*")
            .eq("course_id", course_id)
            .order("order")
            .execute()
        )
        course["chapters"] = chapters_res.data or []
        return course

    def export_full(self, course_id: str) -> Optional[Dict]:
        """Get course with chapters → contents → questions."""
        course = self.get_with_chapters(course_id)
        if not course:
            return None
        for chapter in course.get("chapters", []):
            contents_res = (
                self.client.table("contents")
                .select("*")
                .eq("chapter_id", chapter["id"])
                .order("order")
                .execute()
            )
            chapter["contents"] = contents_res.data or []
            for content in chapter["contents"]:
                questions_res = (
                    self.client.table("questions")
                    .select("*")
                    .eq("content_id", content["id"])
                    .execute()
                )
                content["questions"] = questions_res.data or []
        return course
