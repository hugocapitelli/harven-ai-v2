from uuid import uuid4

from sqlalchemy import Column, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import relationship

from database import Base


class ExternalMapping(Base):
    __tablename__ = "external_mappings"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    entity_type = Column(String(50), nullable=False)
    local_id = Column(String, nullable=False)
    external_id = Column(String, nullable=False)
    external_system = Column(String(50), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class MoodleRating(Base):
    __tablename__ = "moodle_ratings"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    session_id = Column(String, nullable=False)
    student_id = Column(String, nullable=False)
    teacher_id = Column(String, nullable=False)
    rating = Column(Float, nullable=True)
    feedback = Column(Text, nullable=True)
    rated_at = Column(DateTime, server_default=func.now(), nullable=True)


class IntegrationLog(Base):
    __tablename__ = "integration_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    system = Column(String(50), nullable=False)
    operation = Column(String(100), nullable=False)
    direction = Column(String(20), nullable=True)
    status = Column(String(20), nullable=False)
    records_processed = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class TokenUsage(Base):
    __tablename__ = "token_usage"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    usage_date = Column(Date, nullable=False)
    tokens_used = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    __table_args__ = (UniqueConstraint("user_id", "usage_date", name="uq_user_token_date"),)

    user = relationship("User", back_populates="token_usage")


class SessionReview(Base):
    __tablename__ = "session_reviews"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    session_id = Column(String, ForeignKey("chat_sessions.id"), nullable=False)
    reviewer_id = Column(String, ForeignKey("users.id"), nullable=False)
    rating = Column(Float, nullable=True)
    feedback = Column(Text, nullable=True)
    status = Column(String(20), default="pending")
    student_reply = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    session = relationship("ChatSession", back_populates="reviews")
    reviewer = relationship("User")
