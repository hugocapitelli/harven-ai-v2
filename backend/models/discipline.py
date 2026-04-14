from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import relationship

from database import Base


class Discipline(Base):
    __tablename__ = "disciplines"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    name = Column(String(255), nullable=False)
    code = Column(String(50), unique=True, nullable=False)
    semester = Column(String(20), nullable=True)
    description = Column(Text, nullable=True)
    image_url = Column(String(500), nullable=True)
    jacad_code = Column(String(50), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    teachers = relationship("DisciplineTeacher", back_populates="discipline")
    students = relationship("DisciplineStudent", back_populates="discipline")
    courses = relationship("Course", back_populates="discipline")


class DisciplineTeacher(Base):
    __tablename__ = "discipline_teachers"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    discipline_id = Column(String, ForeignKey("disciplines.id"), nullable=False)
    teacher_id = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    discipline = relationship("Discipline", back_populates="teachers")
    teacher = relationship("User", back_populates="taught_disciplines")


class DisciplineStudent(Base):
    __tablename__ = "discipline_students"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    discipline_id = Column(String, ForeignKey("disciplines.id"), nullable=False)
    student_id = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    discipline = relationship("Discipline", back_populates="students")
    student = relationship("User", back_populates="enrolled_disciplines")
