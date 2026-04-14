from sqlalchemy import select, func
from sqlalchemy.orm import Session
from models.settings import SystemSettings, SystemLog, SystemBackup
from .base import BaseRepository


class AdminRepository:
    def __init__(self, db: Session):
        self.db = db

    # --- Settings (singleton) ---

    def get_settings(self):
        query = select(SystemSettings).limit(1)
        return self.db.execute(query).scalar_one_or_none()

    def save_settings(self, data: dict):
        existing = self.get_settings()
        if existing:
            # Preserve URL fields when new value is empty
            url_fields = [k for k in data if k.endswith("_url") or k.endswith("_logo") or k.endswith("_bg")]
            for field in url_fields:
                if not data[field] and hasattr(existing, field) and getattr(existing, field):
                    data.pop(field)
            for key, value in data.items():
                if hasattr(existing, key):
                    setattr(existing, key, value)
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            self.db.refresh(existing)
            return existing
        else:
            obj = SystemSettings(**data)
            self.db.add(obj)
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            self.db.refresh(obj)
            return obj

    # --- Logs ---

    def get_logs(self, skip: int = 0, limit: int = 50, search: str = None):
        query = select(SystemLog)
        if search:
            pattern = f"%{search}%"
            query = query.where(
                (SystemLog.msg.ilike(pattern)) | (SystemLog.author.ilike(pattern))
            )
        count_query = select(func.count()).select_from(query.subquery())
        total = self.db.execute(count_query).scalar() or 0
        query = query.order_by(SystemLog.created_at.desc()).offset(skip).limit(limit)
        rows = self.db.execute(query).scalars().all()
        return rows, total

    def create_log(self, data: dict):
        log = SystemLog(**data)
        self.db.add(log)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(log)
        return log

    # --- Backups ---

    def get_backups(self):
        query = select(SystemBackup).order_by(SystemBackup.created_at.desc())
        return self.db.execute(query).scalars().all()

    def create_backup(self, data: dict):
        backup = SystemBackup(**data)
        self.db.add(backup)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(backup)
        return backup

    def delete_backup(self, backup_id: str) -> bool:
        obj = self.db.get(SystemBackup, backup_id)
        if not obj:
            return False
        self.db.delete(obj)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return True
