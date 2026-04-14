from sqlalchemy import select, func
from sqlalchemy.orm import Session
from models.user import User
from .base import BaseRepository


class UserRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, User)

    def get_by_ra(self, ra: str):
        query = select(User).where(User.ra == ra)
        return self.db.execute(query).scalar_one_or_none()

    def search(self, query_str: str, role: str = None, skip: int = 0, limit: int = 20):
        pattern = f"%{query_str}%"
        query = select(User).where(
            (User.name.ilike(pattern)) | (User.email.ilike(pattern)) | (User.ra.ilike(pattern))
        )
        if role:
            query = query.where(User.role == role)
        count_query = select(func.count()).select_from(query.subquery())
        total = self.db.execute(count_query).scalar() or 0
        query = query.offset(skip).limit(limit)
        rows = self.db.execute(query).scalars().all()
        return rows, total
