from sqlalchemy import select, update as sa_update
from sqlalchemy.orm import Session, joinedload
from models.chat import ChatSession, ChatMessage
from .base import BaseRepository


class ChatRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, ChatSession)

    def get_user_sessions(self, user_id: str):
        query = (
            select(ChatSession)
            .options(joinedload(ChatSession.messages))
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.created_at.desc())
        )
        return self.db.execute(query).scalars().unique().all()

    def get_by_content_user(self, content_id: str, user_id: str):
        query = select(ChatSession).where(
            ChatSession.content_id == content_id,
            ChatSession.user_id == user_id,
        )
        return self.db.execute(query).scalar_one_or_none()

    def add_message(self, session_id: str, data: dict):
        data["session_id"] = session_id
        msg = ChatMessage(**data)
        self.db.add(msg)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(msg)
        return msg
