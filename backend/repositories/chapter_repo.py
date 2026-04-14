from sqlalchemy import select
from sqlalchemy.orm import Session
from models.course import Chapter
from .base import BaseRepository


class ChapterRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, Chapter)

    def get_by_course(self, course_id: str):
        query = (
            select(Chapter)
            .where(Chapter.course_id == course_id)
            .order_by(Chapter.order.asc())
        )
        return self.db.execute(query).scalars().all()
