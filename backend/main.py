"""Harven AI Platform v2.0.0 — Main Application."""

import os
import logging
from datetime import datetime
from contextlib import asynccontextmanager
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import (
    FastAPI,
    HTTPException,
    Depends,
    UploadFile,
    File,
    Request,
    Query,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import get_settings
from database import get_db, init_db
from auth import verify_password, create_access_token, get_current_user, require_role, hash_password
from models import (
    User,
    Discipline,
    DisciplineTeacher,
    DisciplineStudent,
    Course,
    Chapter,
    Content,
    Question,
)
from repositories import (
    UserRepository,
    DisciplineRepository,
    CourseRepository,
    ChapterRepository,
    ContentRepository,
    QuestionRepository,
)
from services.storage_service import StorageService

# ============================================
# LOGGING
# ============================================
logger = logging.getLogger("harven")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# ============================================
# REQUEST / RESPONSE SCHEMAS
# ============================================

# -- Auth --
class LoginRequest(BaseModel):
    ra: str = Field(..., min_length=1, max_length=50)
    password: str = Field(..., min_length=1, max_length=128)


# -- User --
class UserCreate(BaseModel):
    ra: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=255)
    email: Optional[str] = None
    role: str = Field(default="STUDENT")
    password: str = Field(..., min_length=6, max_length=128)


class UserUpdate(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None


# -- Discipline --
class DisciplineCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    code: str = Field(..., min_length=1, max_length=50)
    semester: Optional[str] = None
    description: Optional[str] = None


class DisciplineUpdate(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    semester: Optional[str] = None
    description: Optional[str] = None


class TeacherAdd(BaseModel):
    teacher_id: str


class StudentAdd(BaseModel):
    student_id: str


class StudentBatchAdd(BaseModel):
    student_ids: List[str]


# -- Course --
class CourseCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    instructor_id: Optional[str] = None
    discipline_id: Optional[str] = None
    status: str = "draft"


class CourseUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    instructor_id: Optional[str] = None


# -- Chapter --
class ChapterCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    order: int = 0


class ChapterUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    order: Optional[int] = None


# -- Content --
class ContentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    content_type: str
    body: Optional[str] = None
    media_url: Optional[str] = None
    order: int = 0


class ContentUpdate(BaseModel):
    title: Optional[str] = None
    content_type: Optional[str] = None
    body: Optional[str] = None
    media_url: Optional[str] = None
    order: Optional[int] = None


# -- Question --
class QuestionItem(BaseModel):
    question_text: str
    expected_answer: Optional[str] = None
    difficulty: Optional[str] = None
    skill: Optional[str] = None
    followup_prompts: Optional[list] = None


class QuestionBatchCreate(BaseModel):
    items: List[QuestionItem]


class QuestionUpdate(BaseModel):
    question_text: Optional[str] = None
    expected_answer: Optional[str] = None
    difficulty: Optional[str] = None
    skill: Optional[str] = None
    followup_prompts: Optional[list] = None
    status: Optional[str] = None


class QuestionBatchUpdate(BaseModel):
    items: List[QuestionItem]


# ============================================
# CONSTANTS
# ============================================
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
ALLOWED_CONTENT_TYPES = {
    *ALLOWED_IMAGE_TYPES,
    "application/pdf",
    "video/mp4",
    "video/quicktime",
    "video/webm",
    "audio/mpeg",
    "audio/wav",
    "audio/ogg",
    "application/msword",
    "text/plain",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


# ============================================
# MIDDLEWARE
# ============================================
class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject requests exceeding size limit based on Content-Length header."""

    def __init__(self, app, default_max: int = 10 * 1024 * 1024, upload_max: int = 50 * 1024 * 1024):
        super().__init__(app)
        self.default_max = default_max
        self.upload_max = upload_max

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            length = int(content_length)
            is_upload = "upload" in request.url.path or "avatar" in request.url.path or "image" in request.url.path
            limit = self.upload_max if is_upload else self.default_max
            if length > limit:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body too large (max {limit // (1024 * 1024)}MB)"},
                )
        return await call_next(request)


# ============================================
# HELPERS
# ============================================
def model_to_dict(obj, exclude: set | None = None) -> dict | None:
    """Convert a SQLAlchemy model instance to a plain dict."""
    if obj is None:
        return None
    exclude = exclude or set()
    result = {}
    for c in obj.__table__.columns:
        if c.name in exclude:
            continue
        val = getattr(obj, c.name)
        if isinstance(val, datetime):
            result[c.name] = val.isoformat()
        else:
            result[c.name] = val
    return result


def _build_update_dict(schema: BaseModel) -> dict:
    """Extract only the non-None fields from a Pydantic schema for partial update."""
    return {k: v for k, v in schema.model_dump().items() if v is not None}


def _normalize_role(role: str) -> str:
    """Normalize TEACHER → INSTRUCTOR for frontend compatibility."""
    return "INSTRUCTOR" if role == "TEACHER" else role


def _db_role(role: str | None) -> str | None:
    """Normalize INSTRUCTOR → TEACHER for database storage."""
    if role is None:
        return None
    upper = role.upper()
    return "TEACHER" if upper == "INSTRUCTOR" else upper


# ============================================
# APP SETUP
# ============================================
limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Harven AI Platform v2.0.0 started")
    yield
    logger.info("Shutting down...")


settings = get_settings()

app = FastAPI(
    title="Harven AI Platform",
    version="2.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        settings.FRONTEND_URL,
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

storage = StorageService()

# Serve uploaded files
upload_dir = settings.UPLOAD_DIR
os.makedirs(upload_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=upload_dir), name="uploads")


# ============================================
# HEALTH
# ============================================
@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "service": "Harven AI Platform", "version": "2.0.0"}


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy"}


# ============================================
# AUTH
# ============================================
@app.post("/auth/login", tags=["Auth"])
@limiter.limit("5/minute")
async def login(request: Request, body: LoginRequest, db: Session = Depends(get_db)):
    user_repo = UserRepository(db)
    user = user_repo.get_by_ra(body.ra)
    if not user or not user.password_hash:
        raise HTTPException(status_code=401, detail="Credenciais invalidas")

    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciais invalidas")

    role = _normalize_role(user.role)
    token = create_access_token(user.id, role)

    return {
        "token": token,
        "user": {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": role,
            "ra": user.ra,
            "avatar_url": user.avatar_url,
        },
    }


# ============================================
# USERS
# ============================================
@app.get("/users", tags=["Users"])
async def list_users(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    role: Optional[str] = None,
    q: Optional[str] = None,
    current_user: User = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    db: Session = Depends(get_db),
):
    user_repo = UserRepository(db)
    target_role = _db_role(role) if role else None

    if q:
        users, total = user_repo.search(q, role=target_role, skip=(page - 1) * per_page, limit=per_page)
    else:
        filters = {"role": target_role} if target_role else None
        users, total = user_repo.get_all(
            filters=filters,
            order_by="name",
            offset=(page - 1) * per_page,
            limit=per_page,
        )

    return {
        "data": [model_to_dict(u, exclude={"password_hash"}) for u in users],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@app.post("/users", tags=["Users"], status_code=201)
async def create_user(
    body: UserCreate,
    current_user: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    user_repo = UserRepository(db)
    data = {
        "ra": body.ra,
        "name": body.name,
        "email": body.email,
        "role": _db_role(body.role) or "STUDENT",
        "password_hash": hash_password(body.password),
    }
    try:
        user = user_repo.create(data)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="RA ja cadastrado")
    return model_to_dict(user, exclude={"password_hash"})


@app.post("/users/batch", tags=["Users"], status_code=201)
async def batch_create_users(
    users: List[UserCreate],
    current_user: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    user_repo = UserRepository(db)
    data_list = [
        {
            "ra": u.ra,
            "name": u.name,
            "email": u.email,
            "role": _db_role(u.role) or "STUDENT",
            "password_hash": hash_password(u.password),
        }
        for u in users
    ]
    try:
        created = user_repo.create_many(data_list)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Um ou mais RAs ja cadastrados")
    return {"message": f"{len(created)} usuarios criados", "count": len(created)}


@app.get("/users/{user_id}", tags=["Users"])
async def get_user(
    user_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_repo = UserRepository(db)
    user = user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    return model_to_dict(user, exclude={"password_hash"})


@app.put("/users/{user_id}", tags=["Users"])
async def update_user(
    user_id: str,
    body: UserUpdate,
    current_user: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    user_repo = UserRepository(db)
    data = _build_update_dict(body)
    if "password" in data:
        data["password_hash"] = hash_password(data.pop("password"))
    if "role" in data:
        data["role"] = _db_role(data["role"])
    if not data:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    user = user_repo.update(user_id, data)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    return model_to_dict(user, exclude={"password_hash"})


@app.post("/users/{user_id}/avatar", tags=["Users"])
async def upload_avatar(
    user_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de imagem nao permitido")

    url = await storage.save_file(file, subdir="avatars")
    user_repo = UserRepository(db)
    user = user_repo.update(user_id, {"avatar_url": url})
    if not user:
        raise HTTPException(status_code=404, detail="Usuario nao encontrado")
    return {"avatar_url": url}


# ============================================
# DISCIPLINES
# ============================================
@app.get("/disciplines", tags=["Disciplines"])
async def list_disciplines(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    disc_repo = DisciplineRepository(db)

    # Role-based filtering
    filters = None
    if current_user.role == "TEACHER":
        teacher_links = disc_repo.get_teachers_for_user(current_user.id) if hasattr(disc_repo, "get_teachers_for_user") else []
        if not teacher_links:
            # Fallback: query discipline_teachers directly
            from sqlalchemy import select
            q = select(DisciplineTeacher.discipline_id).where(DisciplineTeacher.teacher_id == current_user.id)
            ids = [r[0] for r in db.execute(q).all()]
            if ids:
                filters = {"id": ids}
            else:
                return {"data": [], "total": 0, "page": page, "per_page": per_page}
    elif current_user.role == "STUDENT":
        from sqlalchemy import select
        q = select(DisciplineStudent.discipline_id).where(DisciplineStudent.student_id == current_user.id)
        ids = [r[0] for r in db.execute(q).all()]
        if ids:
            filters = {"id": ids}
        else:
            return {"data": [], "total": 0, "page": page, "per_page": per_page}

    disciplines, total = disc_repo.get_all(
        filters=filters,
        order_by="name",
        offset=(page - 1) * per_page,
        limit=per_page,
    )
    return {
        "data": [model_to_dict(d) for d in disciplines],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@app.post("/disciplines", tags=["Disciplines"], status_code=201)
async def create_discipline(
    body: DisciplineCreate,
    current_user: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    disc_repo = DisciplineRepository(db)
    try:
        discipline = disc_repo.create(body.model_dump())
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Codigo de disciplina ja existe")
    return model_to_dict(discipline)


@app.get("/disciplines/{discipline_id}", tags=["Disciplines"])
async def get_discipline(
    discipline_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    disc_repo = DisciplineRepository(db)
    discipline = disc_repo.get_by_id(discipline_id)
    if not discipline:
        raise HTTPException(status_code=404, detail="Disciplina nao encontrada")
    return model_to_dict(discipline)


@app.put("/disciplines/{discipline_id}", tags=["Disciplines"])
async def update_discipline(
    discipline_id: str,
    body: DisciplineUpdate,
    current_user: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    disc_repo = DisciplineRepository(db)
    data = _build_update_dict(body)
    if not data:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    discipline = disc_repo.update(discipline_id, data)
    if not discipline:
        raise HTTPException(status_code=404, detail="Disciplina nao encontrada")
    return model_to_dict(discipline)


@app.get("/disciplines/{discipline_id}/teachers", tags=["Disciplines"])
async def list_discipline_teachers(
    discipline_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    disc_repo = DisciplineRepository(db)
    if not disc_repo.get_by_id(discipline_id):
        raise HTTPException(status_code=404, detail="Disciplina nao encontrada")
    links = disc_repo.get_teachers(discipline_id)
    return [
        {
            "id": link.id,
            "teacher_id": link.teacher_id,
            "teacher": model_to_dict(link.teacher, exclude={"password_hash"}) if link.teacher else None,
        }
        for link in links
    ]


@app.post("/disciplines/{discipline_id}/teachers", tags=["Disciplines"], status_code=201)
async def add_discipline_teacher(
    discipline_id: str,
    body: TeacherAdd,
    current_user: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    disc_repo = DisciplineRepository(db)
    if not disc_repo.get_by_id(discipline_id):
        raise HTTPException(status_code=404, detail="Disciplina nao encontrada")
    try:
        link = disc_repo.add_teacher(discipline_id, body.teacher_id)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Professor ja vinculado a esta disciplina")
    return {"id": link.id, "discipline_id": discipline_id, "teacher_id": body.teacher_id}


@app.delete("/disciplines/{discipline_id}/teachers/{teacher_id}", tags=["Disciplines"])
async def remove_discipline_teacher(
    discipline_id: str,
    teacher_id: str,
    current_user: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    disc_repo = DisciplineRepository(db)
    removed = disc_repo.remove_teacher(discipline_id, teacher_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Vinculo nao encontrado")
    return {"message": "Professor removido da disciplina"}


@app.get("/disciplines/{discipline_id}/students", tags=["Disciplines"])
async def list_discipline_students(
    discipline_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    disc_repo = DisciplineRepository(db)
    if not disc_repo.get_by_id(discipline_id):
        raise HTTPException(status_code=404, detail="Disciplina nao encontrada")
    links = disc_repo.get_students(discipline_id)
    return [
        {
            "id": link.id,
            "student_id": link.student_id,
            "student": model_to_dict(link.student, exclude={"password_hash"}) if link.student else None,
        }
        for link in links
    ]


@app.post("/disciplines/{discipline_id}/students", tags=["Disciplines"], status_code=201)
async def add_discipline_student(
    discipline_id: str,
    body: StudentAdd,
    current_user: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    disc_repo = DisciplineRepository(db)
    if not disc_repo.get_by_id(discipline_id):
        raise HTTPException(status_code=404, detail="Disciplina nao encontrada")
    try:
        link = disc_repo.add_student(discipline_id, body.student_id)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Aluno ja vinculado a esta disciplina")
    return {"id": link.id, "discipline_id": discipline_id, "student_id": body.student_id}


@app.post("/disciplines/{discipline_id}/students/batch", tags=["Disciplines"], status_code=201)
async def batch_add_discipline_students(
    discipline_id: str,
    body: StudentBatchAdd,
    current_user: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    disc_repo = DisciplineRepository(db)
    if not disc_repo.get_by_id(discipline_id):
        raise HTTPException(status_code=404, detail="Disciplina nao encontrada")
    try:
        created = disc_repo.add_students_batch(discipline_id, body.student_ids)
    except IntegrityError:
        raise HTTPException(status_code=409, detail="Um ou mais alunos ja vinculados")
    return {"message": f"{len(created)} alunos adicionados", "count": len(created)}


@app.delete("/disciplines/{discipline_id}/students/{student_id}", tags=["Disciplines"])
async def remove_discipline_student(
    discipline_id: str,
    student_id: str,
    current_user: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    disc_repo = DisciplineRepository(db)
    removed = disc_repo.remove_student(discipline_id, student_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Vinculo nao encontrado")
    return {"message": "Aluno removido da disciplina"}


@app.post("/disciplines/{discipline_id}/image", tags=["Disciplines"])
async def upload_discipline_image(
    discipline_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de imagem nao permitido")
    disc_repo = DisciplineRepository(db)
    if not disc_repo.get_by_id(discipline_id):
        raise HTTPException(status_code=404, detail="Disciplina nao encontrada")

    url = await storage.save_file(file, subdir="disciplines")
    disc_repo.update(discipline_id, {"image_url": url})
    return {"image_url": url}


# ============================================
# COURSES
# ============================================
@app.get("/courses", tags=["Courses"])
async def list_courses(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    discipline_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course_repo = CourseRepository(db)
    filters = {}
    if discipline_id:
        filters["discipline_id"] = discipline_id

    courses, total = course_repo.get_all(
        filters=filters if filters else None,
        order_by="created_at",
        desc=True,
        offset=(page - 1) * per_page,
        limit=per_page,
    )
    return {
        "data": [model_to_dict(c) for c in courses],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@app.post("/courses", tags=["Courses"], status_code=201)
async def create_course(
    body: CourseCreate,
    current_user: User = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    db: Session = Depends(get_db),
):
    course_repo = CourseRepository(db)
    data = body.model_dump()
    if not data.get("instructor_id"):
        data["instructor_id"] = current_user.id
    course = course_repo.create(data)
    return model_to_dict(course)


@app.get("/courses/{course_id}", tags=["Courses"])
async def get_course(
    course_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course_repo = CourseRepository(db)
    course = course_repo.get_with_chapters(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso nao encontrado")

    result = model_to_dict(course)
    result["chapters"] = [model_to_dict(ch) for ch in course.chapters]
    return result


@app.get("/courses/{course_id}/export", tags=["Courses"])
async def export_course(
    course_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course_repo = CourseRepository(db)
    course = course_repo.export_full(course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso nao encontrado")

    result = model_to_dict(course)
    result["chapters"] = []
    for chapter in course.chapters:
        ch_dict = model_to_dict(chapter)
        ch_dict["contents"] = []
        for content in chapter.contents:
            ct_dict = model_to_dict(content)
            ct_dict["questions"] = [model_to_dict(q) for q in content.questions]
            ch_dict["contents"].append(ct_dict)
        result["chapters"].append(ch_dict)
    return result


@app.put("/courses/{course_id}", tags=["Courses"])
async def update_course(
    course_id: str,
    body: CourseUpdate,
    current_user: User = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    db: Session = Depends(get_db),
):
    course_repo = CourseRepository(db)
    data = _build_update_dict(body)
    if not data:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    course = course_repo.update(course_id, data)
    if not course:
        raise HTTPException(status_code=404, detail="Curso nao encontrado")
    return model_to_dict(course)


@app.delete("/courses/{course_id}", tags=["Courses"])
async def delete_course(
    course_id: str,
    current_user: User = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
):
    course_repo = CourseRepository(db)
    if not course_repo.delete(course_id):
        raise HTTPException(status_code=404, detail="Curso nao encontrado")
    return {"message": "Curso removido"}


@app.post("/courses/{course_id}/image", tags=["Courses"])
async def upload_course_image(
    course_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    db: Session = Depends(get_db),
):
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Tipo de imagem nao permitido")
    course_repo = CourseRepository(db)
    if not course_repo.get_by_id(course_id):
        raise HTTPException(status_code=404, detail="Curso nao encontrado")

    url = await storage.save_file(file, subdir="courses")
    course_repo.update(course_id, {"image_url": url})
    return {"image_url": url}


@app.get("/classes/{class_id}/courses", tags=["Courses"])
async def list_discipline_courses(
    class_id: str,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course_repo = CourseRepository(db)
    courses, total = course_repo.get_all(
        filters={"discipline_id": class_id},
        order_by="created_at",
        desc=True,
        offset=(page - 1) * per_page,
        limit=per_page,
    )
    return {
        "data": [model_to_dict(c) for c in courses],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@app.post("/classes/{class_id}/courses", tags=["Courses"], status_code=201)
async def create_discipline_course(
    class_id: str,
    body: CourseCreate,
    current_user: User = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    db: Session = Depends(get_db),
):
    course_repo = CourseRepository(db)
    data = body.model_dump()
    data["discipline_id"] = class_id
    if not data.get("instructor_id"):
        data["instructor_id"] = current_user.id
    data["status"] = "Ativa"
    course = course_repo.create(data)
    return model_to_dict(course)


# ============================================
# CHAPTERS
# ============================================
@app.get("/courses/{course_id}/chapters", tags=["Chapters"])
async def list_chapters(
    course_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    chapter_repo = ChapterRepository(db)
    chapters = chapter_repo.get_by_course(course_id)
    return [model_to_dict(ch) for ch in chapters]


@app.post("/courses/{course_id}/chapters", tags=["Chapters"], status_code=201)
async def create_chapter(
    course_id: str,
    body: ChapterCreate,
    current_user: User = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    db: Session = Depends(get_db),
):
    # Verify course exists
    course_repo = CourseRepository(db)
    if not course_repo.get_by_id(course_id):
        raise HTTPException(status_code=404, detail="Curso nao encontrado")

    chapter_repo = ChapterRepository(db)
    data = body.model_dump()
    data["course_id"] = course_id
    chapter = chapter_repo.create(data)
    return model_to_dict(chapter)


@app.put("/chapters/{chapter_id}", tags=["Chapters"])
async def update_chapter(
    chapter_id: str,
    body: ChapterUpdate,
    current_user: User = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    db: Session = Depends(get_db),
):
    chapter_repo = ChapterRepository(db)
    data = _build_update_dict(body)
    if not data:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    chapter = chapter_repo.update(chapter_id, data)
    if not chapter:
        raise HTTPException(status_code=404, detail="Capitulo nao encontrado")
    return model_to_dict(chapter)


@app.delete("/chapters/{chapter_id}", tags=["Chapters"])
async def delete_chapter(
    chapter_id: str,
    current_user: User = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    db: Session = Depends(get_db),
):
    chapter_repo = ChapterRepository(db)
    if not chapter_repo.delete(chapter_id):
        raise HTTPException(status_code=404, detail="Capitulo nao encontrado")
    return {"message": "Capitulo removido"}


# ============================================
# CONTENTS
# ============================================
@app.get("/chapters/{chapter_id}/contents", tags=["Contents"])
async def list_contents(
    chapter_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content_repo = ContentRepository(db)
    contents = content_repo.get_by_chapter(chapter_id)
    return [model_to_dict(c) for c in contents]


@app.post("/chapters/{chapter_id}/contents", tags=["Contents"], status_code=201)
async def create_content(
    chapter_id: str,
    body: ContentCreate,
    current_user: User = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    db: Session = Depends(get_db),
):
    chapter_repo = ChapterRepository(db)
    if not chapter_repo.get_by_id(chapter_id):
        raise HTTPException(status_code=404, detail="Capitulo nao encontrado")

    content_repo = ContentRepository(db)
    data = body.model_dump()
    data["chapter_id"] = chapter_id
    content = content_repo.create(data)
    return model_to_dict(content)


@app.get("/contents/{content_id}", tags=["Contents"])
async def get_content(
    content_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content_repo = ContentRepository(db)
    content = content_repo.get_by_id(content_id)
    if not content:
        raise HTTPException(status_code=404, detail="Conteudo nao encontrado")

    result = model_to_dict(content)
    question_repo = QuestionRepository(db)
    questions = question_repo.get_by_content(content_id)
    result["questions"] = [model_to_dict(q) for q in questions]
    return result


@app.put("/contents/{content_id}", tags=["Contents"])
async def update_content(
    content_id: str,
    body: ContentUpdate,
    current_user: User = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    db: Session = Depends(get_db),
):
    content_repo = ContentRepository(db)
    data = _build_update_dict(body)
    if not data:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    content = content_repo.update(content_id, data)
    if not content:
        raise HTTPException(status_code=404, detail="Conteudo nao encontrado")
    return model_to_dict(content)


@app.delete("/contents/{content_id}", tags=["Contents"])
async def delete_content(
    content_id: str,
    current_user: User = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    db: Session = Depends(get_db),
):
    content_repo = ContentRepository(db)
    if not content_repo.delete(content_id):
        raise HTTPException(status_code=404, detail="Conteudo nao encontrado")
    return {"message": "Conteudo removido"}


@app.post("/chapters/{chapter_id}/upload", tags=["Contents"])
async def upload_chapter_file(
    chapter_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    db: Session = Depends(get_db),
):
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail=f"Tipo de arquivo nao permitido: {file.content_type}")

    chapter_repo = ChapterRepository(db)
    if not chapter_repo.get_by_id(chapter_id):
        raise HTTPException(status_code=404, detail="Capitulo nao encontrado")

    url = await storage.save_file(file, subdir="contents")

    # Determine content type from MIME
    mime = file.content_type or ""
    if mime.startswith("video/"):
        ctype = "video"
    elif mime.startswith("audio/"):
        ctype = "audio"
    elif mime == "application/pdf":
        ctype = "pdf"
    elif mime.startswith("image/"):
        ctype = "image"
    else:
        ctype = "document"

    return {
        "url": url,
        "filename": file.filename,
        "type": ctype,
        "size": file.size,
    }


# ============================================
# QUESTIONS
# ============================================
@app.get("/contents/{content_id}/questions", tags=["Questions"])
async def list_questions(
    content_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    question_repo = QuestionRepository(db)
    questions = question_repo.get_by_content(content_id)
    return [model_to_dict(q) for q in questions]


@app.post("/contents/{content_id}/questions", tags=["Questions"], status_code=201)
async def create_questions(
    content_id: str,
    body: QuestionBatchCreate,
    current_user: User = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    db: Session = Depends(get_db),
):
    content_repo = ContentRepository(db)
    if not content_repo.get_by_id(content_id):
        raise HTTPException(status_code=404, detail="Conteudo nao encontrado")

    question_repo = QuestionRepository(db)
    items = [item.model_dump() for item in body.items]
    questions = question_repo.batch_create(content_id, items)
    return [model_to_dict(q) for q in questions]


@app.put("/questions/{question_id}", tags=["Questions"])
async def update_question(
    question_id: str,
    body: QuestionUpdate,
    current_user: User = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    db: Session = Depends(get_db),
):
    question_repo = QuestionRepository(db)
    data = _build_update_dict(body)
    if not data:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    question = question_repo.update(question_id, data)
    if not question:
        raise HTTPException(status_code=404, detail="Questao nao encontrada")
    return model_to_dict(question)


@app.put("/contents/{content_id}/questions/batch", tags=["Questions"])
async def batch_update_questions(
    content_id: str,
    body: QuestionBatchUpdate,
    current_user: User = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    db: Session = Depends(get_db),
):
    try:
        # Mark existing questions for replacement
        existing = db.query(Question).filter(Question.content_id == content_id).all()
        for q in existing:
            q.status = "replacing"
        db.flush()

        # Insert new questions
        new_questions = []
        for item in body.items:
            data = item.model_dump()
            data["content_id"] = content_id
            obj = Question(**data)
            db.add(obj)
            new_questions.append(obj)
        db.flush()

        # Remove old questions
        for q in existing:
            db.delete(q)

        db.commit()
        for q in new_questions:
            db.refresh(q)
        return [model_to_dict(q) for q in new_questions]
    except Exception as e:
        db.rollback()
        logger.error(f"Batch update questions error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Erro ao atualizar questoes em lote")


@app.delete("/questions/{question_id}", tags=["Questions"])
async def delete_question(
    question_id: str,
    current_user: User = Depends(require_role("ADMIN", "TEACHER", "INSTRUCTOR")),
    db: Session = Depends(get_db),
):
    question_repo = QuestionRepository(db)
    if not question_repo.delete(question_id):
        raise HTTPException(status_code=404, detail="Questao nao encontrada")
    return {"message": "Questao removida"}


# ---------------------------------------------------------------------------
# External route modules
# ---------------------------------------------------------------------------
from routes_admin import router as admin_router
from routes_ai import router as ai_router

app.include_router(admin_router)
app.include_router(ai_router)
