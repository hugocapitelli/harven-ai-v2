from sqlalchemy import select, func, update
from sqlalchemy.orm import Session
from models.notification import Notification
from .base import BaseRepository


class NotificationRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, Notification)

    def get_by_user(self, user_id: str, skip: int = 0, limit: int = 50):
        query = (
            select(Notification)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
        )
        count_query = select(func.count()).select_from(
            select(Notification).where(Notification.user_id == user_id).subquery()
        )
        total = self.db.execute(count_query).scalar() or 0
        query = query.offset(skip).limit(limit)
        rows = self.db.execute(query).scalars().all()
        return rows, total

    def count_unread(self, user_id: str) -> int:
        query = select(func.count()).where(
            Notification.user_id == user_id,
            Notification.read.is_(False),
        )
        return self.db.execute(query).scalar() or 0

    def mark_read(self, notification_id: str):
        stmt = (
            update(Notification)
            .where(Notification.id == notification_id)
            .values(read=True)
        )
        self.db.execute(stmt)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def mark_all_read(self, user_id: str) -> int:
        stmt = (
            update(Notification)
            .where(Notification.user_id == user_id, Notification.read.is_(False))
            .values(read=True)
        )
        result = self.db.execute(stmt)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return result.rowcount
