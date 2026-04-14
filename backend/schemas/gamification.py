from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class ActivityCreate(BaseModel):
    type: str = Field(..., min_length=1)
    description: Optional[str] = None
    points: int = Field(0, ge=0)
    metadata: Optional[dict] = None


class AchievementResponse(BaseModel):
    id: str
    user_id: str
    achievement_id: str
    unlocked_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class CertificateCreate(BaseModel):
    user_id: str
    course_id: str
    discipline_id: Optional[str] = None
    title: str = Field(..., min_length=1)
    grade: Optional[float] = None
