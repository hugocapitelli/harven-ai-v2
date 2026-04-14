from sqlalchemy import select, func
from sqlalchemy.orm import Session, joinedload
from models.course import Course
from models.course import Chapter, Content, Question
from .base import BaseRepository


class CourseRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, Course)

    def get_with_chapters(self, course_id: str):
        query = (
            select(Course)
            .options(joinedload(Course.chapters))
            .where(Course.id == course_id)
        )
        return self.db.execute(query).scalars().unique().first()

    def export_full(self, course_id: str):
        query = (
            select(Course)
            .options(
                joinedload(Course.chapters)
                .joinedload(Chapter.contents)
                .joinedload(Content.questions)
            )
            .where(Course.id == course_id)
        )
        return self.db.execute(query).scalars().unique().first()
