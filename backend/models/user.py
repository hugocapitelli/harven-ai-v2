from uuid import uuid4

from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.orm import relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    ra = Column(String(50), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    email = Column(String(255), nullable=True)
    role = Column(String(20), nullable=False)
    password_hash = Column(String(255), nullable=True)
    avatar_url = Column(String(500), nullable=True)
    moodle_user_id = Column(String(100), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    taught_disciplines = relationship("DisciplineTeacher", back_populates="teacher")
    enrolled_disciplines = relationship("DisciplineStudent", back_populates="student")
    courses = relationship("Course", back_populates="instructor")
    activities = relationship("UserActivity", back_populates="user")
    stats = relationship("UserStats", back_populates="user", uselist=False)
    achievements = relationship("UserAchievement", back_populates="user")
    certificates = relationship("Certificate", back_populates="user")
    notifications = relationship("Notification", back_populates="user")
    chat_sessions = relationship("ChatSession", back_populates="user")
    token_usage = relationship("TokenUsage", back_populates="user")
