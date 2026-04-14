from sqlalchemy import select
from sqlalchemy.orm import Session
from models.course import Question
from .base import BaseRepository


class QuestionRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, Question)

    def get_by_content(self, content_id: str):
        query = select(Question).where(Question.content_id == content_id)
        return self.db.execute(query).scalars().all()

    def batch_create(self, content_id: str, questions: list):
        objects = []
        for q in questions:
            q["content_id"] = content_id
            objects.append(Question(**q))
        self.db.add_all(objects)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        for obj in objects:
            self.db.refresh(obj)
        return objects
