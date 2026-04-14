from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    ra: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    token: str
    user: dict

    model_config = {"from_attributes": True}
