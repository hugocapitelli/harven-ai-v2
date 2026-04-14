from pydantic import BaseModel, Field
from typing import Optional


class NotificationCreate(BaseModel):
    user_id: str
    title: str = Field(..., min_length=1, max_length=200)
    message: str = Field(..., min_length=1)
    type: str = Field("info", pattern="^(info|success|warning|error)$")
    link: Optional[str] = None
