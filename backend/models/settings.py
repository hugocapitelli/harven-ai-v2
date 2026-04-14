from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSON

from database import Base


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    platform_name = Column(String(255), nullable=True)
    base_url = Column(String(500), nullable=True)
    primary_color = Column(String(20), nullable=True)
    logo_url = Column(String(500), nullable=True)
    login_logo_url = Column(String(500), nullable=True)
    login_bg_url = Column(String(500), nullable=True)
    ai_tutor_enabled = Column(Boolean, default=True)
    gamification_enabled = Column(Boolean, default=True)
    dark_mode_enabled = Column(Boolean, default=False)
    openai_key = Column(String(500), nullable=True)
    moodle_url = Column(String(500), nullable=True)
    moodle_token = Column(String(500), nullable=True)
    smtp_password = Column(String(500), nullable=True)
    jacad_api_key = Column(String(500), nullable=True)
    lti_shared_secret = Column(String(500), nullable=True)
    max_token_limit = Column(Integer, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class SystemLog(Base):
    __tablename__ = "system_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    message = Column(Text, nullable=True)
    author = Column(String(255), nullable=True)
    status = Column(String(50), nullable=True)
    log_type = Column(String(50), nullable=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class SystemBackup(Base):
    __tablename__ = "system_backups"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    filename = Column(String(255), nullable=False)
    size = Column(Integer, nullable=True)
    records_count = Column(Integer, nullable=True)
    status = Column(String(50), default="completed")
    storage_path = Column(String(500), nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
