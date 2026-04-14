from sqlalchemy import select
from sqlalchemy.orm import Session
from models.gamification import UserActivity, UserStats, UserAchievement, Certificate
from models.progress import CourseProgress
from .base import BaseRepository


class GamificationRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, UserActivity)

    # --- Stats ---

    def get_user_stats(self, user_id: str):
        query = select(UserStats).where(UserStats.user_id == user_id)
        stats = self.db.execute(query).scalar_one_or_none()
        if not stats:
            stats = UserStats(user_id=user_id)
            self.db.add(stats)
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            self.db.refresh(stats)
        return stats

    # --- Activities ---

    def get_user_activities(self, user_id: str, skip: int = 0, limit: int = 50):
        query = (
            select(UserActivity)
            .where(UserActivity.user_id == user_id)
            .order_by(UserActivity.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        return self.db.execute(query).scalars().all()

    def add_activity(self, user_id: str, data: dict):
        data["user_id"] = user_id
        activity = UserActivity(**data)
        self.db.add(activity)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(activity)
        return activity

    # --- Achievements ---

    def get_achievements(self, user_id: str):
        query = select(UserAchievement).where(UserAchievement.user_id == user_id)
        return self.db.execute(query).scalars().all()

    def unlock_achievement(self, user_id: str, achievement_id: str):
        obj = UserAchievement(user_id=user_id, achievement_id=achievement_id)
        self.db.add(obj)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(obj)
        return obj

    # --- Certificates ---

    def get_certificates(self, user_id: str):
        query = select(Certificate).where(Certificate.user_id == user_id)
        return self.db.execute(query).scalars().all()

    def issue_certificate(self, data: dict):
        cert = Certificate(**data)
        self.db.add(cert)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(cert)
        return cert

    # --- Progress ---

    def get_course_progress(self, user_id: str, course_id: str):
        query = select(CourseProgress).where(
            CourseProgress.user_id == user_id,
            CourseProgress.course_id == course_id,
        )
        progress = self.db.execute(query).scalar_one_or_none()
        if not progress:
            progress = CourseProgress(user_id=user_id, course_id=course_id)
            self.db.add(progress)
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            self.db.refresh(progress)
        return progress

    def complete_content(self, user_id: str, course_id: str, content_id: str):
        progress = self.get_course_progress(user_id, course_id)
        completed = progress.completed_content_ids or []
        if content_id not in completed:
            completed.append(content_id)
            progress.completed_content_ids = completed
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            self.db.refresh(progress)
        return progress
