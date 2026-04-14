from sqlalchemy.orm import Session
from sqlalchemy import select, func
from typing import Type, TypeVar, Optional, List, Dict, Any

T = TypeVar("T")


class BaseRepository:
    def __init__(self, db: Session, model: Type[T]):
        self.db = db
        self.model = model

    def get_by_id(self, id: str) -> Optional[T]:
        return self.db.get(self.model, id)

    def get_all(self, filters=None, order_by=None, desc=False, limit=None, offset=None) -> tuple[List[T], int]:
        query = select(self.model)
        if filters:
            for key, value in filters.items():
                if isinstance(value, list):
                    query = query.where(getattr(self.model, key).in_(value))
                else:
                    query = query.where(getattr(self.model, key) == value)
        count_query = select(func.count()).select_from(query.subquery())
        total = self.db.execute(count_query).scalar() or 0
        if order_by:
            col = getattr(self.model, order_by)
            query = query.order_by(col.desc() if desc else col.asc())
        if offset is not None:
            query = query.offset(offset)
        if limit is not None:
            query = query.limit(limit)
        rows = self.db.execute(query).scalars().all()
        return rows, total

    def create(self, data: Dict[str, Any]) -> T:
        obj = self.model(**data)
        self.db.add(obj)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(obj)
        return obj

    def create_many(self, data_list: List[Dict[str, Any]]) -> List[T]:
        objects = [self.model(**data) for data in data_list]
        self.db.add_all(objects)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        for obj in objects:
            self.db.refresh(obj)
        return objects

    def update(self, id: str, data: Dict[str, Any]) -> Optional[T]:
        obj = self.get_by_id(id)
        if not obj:
            return None
        for key, value in data.items():
            setattr(obj, key, value)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(obj)
        return obj

    def delete(self, id: str) -> bool:
        obj = self.get_by_id(id)
        if not obj:
            return False
        self.db.delete(obj)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return True

    def delete_where(self, filters: Dict[str, Any]) -> int:
        query = select(self.model)
        for key, value in filters.items():
            query = query.where(getattr(self.model, key) == value)
        objects = self.db.execute(query).scalars().all()
        count = len(objects)
        for obj in objects:
            self.db.delete(obj)
        if count > 0:
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return count

    def upsert(self, data: Dict[str, Any], unique_field: str = "id") -> T:
        if unique_field in data and data[unique_field]:
            query = select(self.model).where(
                getattr(self.model, unique_field) == data[unique_field]
            )
            existing = self.db.execute(query).scalar_one_or_none()
            if existing:
                for key, value in data.items():
                    setattr(existing, key, value)
                try:
                    self.db.commit()
                except Exception:
                    self.db.rollback()
                    raise
                self.db.refresh(existing)
                return existing
        return self.create(data)
