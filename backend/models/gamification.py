from uuid import uuid4

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from database import Base


class UserActivity(Base):
    __tablename__ = "user_activities"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    activity_type = Column(String(50), nullable=False)
    description = Column(Text, nullable=True)
    points = Column(Integer, default=0)
    metadata_ = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    user = relationship("User", back_populates="activities")


class UserStats(Base):
    __tablename__ = "user_stats"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), unique=True, nullable=False)
    courses_completed = Column(Integer, default=0)
    hours_studied = Column(Float, default=0.0)
    average_score = Column(Float, default=0.0)
    streak_days = Column(Integer, default=0)
    total_points = Column(Integer, default=0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="stats")


class UserAchievement(Base):
    __tablename__ = "user_achievements"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    icon = Column(String(100), nullable=True)
    category = Column(String(50), nullable=True)
    rarity = Column(String(20), nullable=True)
    points = Column(Integer, default=0)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    unlocked_at = Column(DateTime, server_default=func.now(), nullable=True)

    user = relationship("User", back_populates="achievements")


class Certificate(Base):
    __tablename__ = "certificates"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    course_id = Column(String, ForeignKey("courses.id"), nullable=False)
    certificate_number = Column(String(100), unique=True, nullable=False)
    issued_at = Column(DateTime, server_default=func.now(), nullable=True)

    user = relationship("User", back_populates="certificates")
    course = relationship("Course", back_populates="certificates")


class CourseProgress(Base):
    __tablename__ = "course_progress"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    course_id = Column(String, ForeignKey("courses.id"), nullable=False)
    progress_percent = Column(Float, default=0.0)
    completed_contents = Column(Integer, default=0)
    total_contents = Column(Integer, default=0)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (UniqueConstraint("user_id", "course_id", name="uq_user_course_progress"),)

    user = relationship("User")
    course = relationship("Course", back_populates="progress")
