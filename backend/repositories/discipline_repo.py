from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload
from models.discipline import Discipline, DisciplineTeacher, DisciplineStudent
from .base import BaseRepository


class DisciplineRepository(BaseRepository):
    def __init__(self, db: Session):
        super().__init__(db, Discipline)

    def add_teacher(self, discipline_id: str, teacher_id: str):
        obj = DisciplineTeacher(discipline_id=discipline_id, teacher_id=teacher_id)
        self.db.add(obj)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(obj)
        return obj

    def remove_teacher(self, discipline_id: str, teacher_id: str) -> int:
        query = select(DisciplineTeacher).where(
            DisciplineTeacher.discipline_id == discipline_id,
            DisciplineTeacher.teacher_id == teacher_id,
        )
        obj = self.db.execute(query).scalar_one_or_none()
        if obj:
            self.db.delete(obj)
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            return 1
        return 0

    def add_student(self, discipline_id: str, student_id: str):
        obj = DisciplineStudent(discipline_id=discipline_id, student_id=student_id)
        self.db.add(obj)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(obj)
        return obj

    def remove_student(self, discipline_id: str, student_id: str) -> int:
        query = select(DisciplineStudent).where(
            DisciplineStudent.discipline_id == discipline_id,
            DisciplineStudent.student_id == student_id,
        )
        obj = self.db.execute(query).scalar_one_or_none()
        if obj:
            self.db.delete(obj)
            try:
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            return 1
        return 0

    def add_students_batch(self, discipline_id: str, student_ids: list):
        objects = [DisciplineStudent(discipline_id=discipline_id, student_id=sid) for sid in student_ids]
        self.db.add_all(objects)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        return objects

    def get_teachers(self, discipline_id: str):
        query = (
            select(DisciplineTeacher)
            .options(joinedload(DisciplineTeacher.teacher))
            .where(DisciplineTeacher.discipline_id == discipline_id)
        )
        return self.db.execute(query).scalars().unique().all()

    def get_students(self, discipline_id: str):
        query = (
            select(DisciplineStudent)
            .options(joinedload(DisciplineStudent.student))
            .where(DisciplineStudent.discipline_id == discipline_id)
        )
        return self.db.execute(query).scalars().unique().all()
