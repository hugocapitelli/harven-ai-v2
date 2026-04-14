from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship

from database import Base


class Course(Base):
    __tablename__ = "courses"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    instructor_id = Column(String, ForeignKey("users.id"), nullable=True)
    discipline_id = Column(String, ForeignKey("disciplines.id"), nullable=True)
    image_url = Column(String(500), nullable=True)
    status = Column(String(20), default="draft")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    instructor = relationship("User", back_populates="courses")
    discipline = relationship("Discipline", back_populates="courses")
    chapters = relationship("Chapter", back_populates="course", order_by="Chapter.order")
    progress = relationship("CourseProgress", back_populates="course")
    certificates = relationship("Certificate", back_populates="course")


class Chapter(Base):
    __tablename__ = "chapters"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    course_id = Column(String, ForeignKey("courses.id"), nullable=False)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    order = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    course = relationship("Course", back_populates="chapters")
    contents = relationship("Content", back_populates="chapter", order_by="Content.order")


class Content(Base):
    __tablename__ = "contents"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    chapter_id = Column(String, ForeignKey("chapters.id"), nullable=False)
    title = Column(String(255), nullable=False)
    content_type = Column(String(50), nullable=False)
    body = Column(Text, nullable=True)
    media_url = Column(String(500), nullable=True)
    audio_url = Column(String(500), nullable=True)
    order = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    chapter = relationship("Chapter", back_populates="contents")
    questions = relationship("Question", back_populates="content")
    chat_sessions = relationship("ChatSession", back_populates="content")


class Question(Base):
    __tablename__ = "questions"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    content_id = Column(String, ForeignKey("contents.id"), nullable=False)
    question_text = Column(Text, nullable=False)
    expected_answer = Column(Text, nullable=True)
    difficulty = Column(String(20), nullable=True)
    skill = Column(String(100), nullable=True)
    followup_prompts = Column(JSON, nullable=True)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    content = relationship("Content", back_populates="questions")
