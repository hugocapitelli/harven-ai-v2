from sqlalchemy import select
from sqlalchemy.orm import Session
from models.course import Content
from .base import BaseRepository


class ContentRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, Content)

    def get_by_chapter(self, chapter_id: str):
        query = (
            select(Content)
            .where(Content.chapter_id == chapter_id)
            .order_by(Content.order.asc())
        )
        return self.db.execute(query).scalars().all()
