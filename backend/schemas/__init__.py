from .auth import LoginRequest, TokenResponse
from .user import UserCreate, UserUpdate, UserResponse, UserBatchCreate
from .discipline import (
    DisciplineCreate, DisciplineUpdate,
    TeacherAssignment, StudentAssignment, StudentBatchAssignment,
)
from .course import (
    CourseCreate, ChapterCreate, ContentCreate, ContentUpdate,
    QuestionCreate, QuestionUpdate, QuestionBatchCreate,
)
from .chat import ChatSessionCreate, ChatMessageCreate, SessionReviewCreate, ReviewReplyCreate
from .settings import SettingsUpdate, SettingsResponse
from .ai import (
    QuestionGenerationRequest, SocraticDialogueRequest,
    AIDetectionRequest, EditResponseRequest, ValidateResponseRequest,
)
from .gamification import ActivityCreate, AchievementResponse, CertificateCreate
from .notification import NotificationCreate
