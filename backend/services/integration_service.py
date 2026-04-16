"""Integration service — JACAD, Moodle and LTI."""
import base64
import hashlib
import hmac
import logging
import re
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums & dataclass
# ---------------------------------------------------------------------------


class IntegrationSystem(str, Enum):
    JACAD = "jacad"
    MOODLE = "moodle"


class SyncDirection(str, Enum):
    IMPORT = "import"
    EXPORT = "export"


class SyncStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"


@dataclass
class SyncResult:
    system: str
    operation: str
    direction: str
    status: str
    records_processed: int
    records_created: int = 0
    records_updated: int = 0
    records_failed: int = 0
    error_message: Optional[str] = None
    details: Optional[List[Dict]] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {k: v for k, v in self.__dict__.items()}
        for k in ("started_at", "completed_at"):
            if d.get(k) and hasattr(d[k], "isoformat"):
                d[k] = d[k].isoformat()
        return d


# ---------------------------------------------------------------------------
# Mock data
# ---------------------------------------------------------------------------

JACAD_MOCK_DATA = {
    "status": {"connected": True, "version": "mock-1.0", "name": "JACAD Mock"},
    "students": [
        {"ra": "ALU001", "name": "Maria Silva", "email": "maria@harven.edu", "course": "Administracao", "status": "ativo"},
        {"ra": "ALU002", "name": "Joao Santos", "email": "joao@harven.edu", "course": "Agronomia", "status": "ativo"},
        {"ra": "ALU003", "name": "Ana Oliveira", "email": "ana@harven.edu", "course": "Veterinaria", "status": "ativo"},
    ],
    "disciplines": [
        {"codigo": "ADM101", "name": "Fundamentos de Gestao", "department": "Administracao", "semester": "2026.1"},
        {"codigo": "AGR201", "name": "Manejo de Solo", "department": "Agronomia", "semester": "2026.1"},
    ],
}

MOODLE_MOCK_DATA = {
    "status": {"connected": True, "sitename": "Moodle Mock", "version": "mock-4.0"},
    "users": [
        {"id": 101, "username": "maria.silva", "fullname": "Maria Silva", "email": "maria@harven.edu"},
        {"id": 102, "username": "joao.santos", "fullname": "Joao Santos", "email": "joao@harven.edu"},
    ],
    "courses": [
        {"id": 1, "fullname": "Fundamentos de Gestao", "shortname": "ADM101"},
        {"id": 2, "fullname": "Manejo de Solo", "shortname": "AGR201"},
    ],
}

# ---------------------------------------------------------------------------
# JacadClient
# ---------------------------------------------------------------------------


class JacadClient:
    def __init__(self, base_url: str = "", api_key: str = ""):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.api_key = api_key
        self.use_mock = not base_url or not api_key

    async def test_connection(self) -> Dict[str, Any]:
        if self.use_mock:
            return {"connected": True, "mode": "mock", "message": "Usando dados mockados (desenvolvimento)", "version": "mock-1.0"}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{self.base_url}/status", headers={"Authorization": f"Bearer {self.api_key}"})
                r.raise_for_status()
                return {"connected": True, "mode": "live", "message": "Conectado ao JACAD", "version": r.json().get("version", "unknown")}
        except Exception as e:
            return {"connected": False, "mode": "error", "message": str(e), "version": None}

    async def get_student_by_ra(self, ra: str) -> Optional[Dict[str, Any]]:
        if self.use_mock:
            return next((s for s in JACAD_MOCK_DATA["students"] if s["ra"] == ra), None)
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{self.base_url}/students/{ra}", headers={"Authorization": f"Bearer {self.api_key}"})
                r.raise_for_status()
                return r.json()
        except Exception:
            return None

    async def get_student_enrollments(self, ra: str) -> List[Dict[str, Any]]:
        if self.use_mock:
            student = await self.get_student_by_ra(ra)
            if student:
                return [{"discipline": d["name"], "status": "enrolled"} for d in JACAD_MOCK_DATA["disciplines"]]
            return []
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{self.base_url}/students/{ra}/enrollments", headers={"Authorization": f"Bearer {self.api_key}"})
                r.raise_for_status()
                return r.json()
        except Exception:
            return []

    async def get_disciplines(self) -> List[Dict[str, Any]]:
        if self.use_mock:
            return JACAD_MOCK_DATA["disciplines"]
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(f"{self.base_url}/disciplines", headers={"Authorization": f"Bearer {self.api_key}"})
                r.raise_for_status()
                return r.json()
        except Exception:
            return []

    async def get_discipline_students(self, discipline_id: str) -> List[Dict[str, Any]]:
        if self.use_mock:
            return JACAD_MOCK_DATA["students"]
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{self.base_url}/disciplines/{discipline_id}/students",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                r.raise_for_status()
                return r.json()
        except Exception:
            return []


# ---------------------------------------------------------------------------
# MoodleClient
# ---------------------------------------------------------------------------


class MoodleClient:
    def __init__(self, base_url: str = "", token: str = ""):
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.token = token
        self.use_mock = not base_url or not token

    async def _request(self, wsfunction: str, params: Optional[Dict] = None) -> Any:
        if self.use_mock:
            raise ConnectionError("Mock mode — no real requests")
        import httpx
        data = {"wstoken": self.token, "wsfunction": wsfunction, "moodlewsrestformat": "json"}
        if params:
            data.update(params)
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{self.base_url}/webservice/rest/server.php", data=data)
            r.raise_for_status()
            return r.json()

    async def test_connection(self) -> Dict[str, Any]:
        if self.use_mock:
            return {"connected": True, "mode": "mock", "message": "Usando dados mockados (desenvolvimento)", "sitename": "Moodle Mock", "version": "mock-4.0"}
        try:
            result = await self._request("core_webservice_get_site_info")
            return {
                "connected": True, "mode": "live",
                "message": "Conectado ao Moodle",
                "sitename": result.get("sitename", ""),
                "version": result.get("release", ""),
            }
        except Exception as e:
            return {"connected": False, "mode": "error", "message": str(e), "sitename": None, "version": None}

    async def get_users(self, criteria: Optional[Dict] = None) -> List[Dict]:
        if self.use_mock:
            return MOODLE_MOCK_DATA["users"]
        return await self._request("core_user_get_users", criteria or {})

    async def get_courses(self) -> List[Dict]:
        if self.use_mock:
            return MOODLE_MOCK_DATA["courses"]
        return await self._request("core_course_get_courses")

    async def create_portfolio_entry(self, user_id: int, data: Dict) -> Dict:
        if self.use_mock:
            return {"success": True, "id": str(uuid4())[:8], "mode": "mock"}
        return await self._request("mod_portfolio_add_entry", {"userid": user_id, **data})

    async def update_grade(self, course_id: int, user_id: int, grade: float, feedback: str = "") -> Dict:
        if self.use_mock:
            return {"success": True, "mode": "mock"}
        return await self._request("core_grades_update_grades", {
            "courseid": course_id, "userid": user_id, "grade": grade, "feedback": feedback,
        })

    @staticmethod
    def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)


# ---------------------------------------------------------------------------
# IntegrationService
# ---------------------------------------------------------------------------


class IntegrationService:
    def __init__(self, client, settings: Optional[Dict[str, str]] = None):
        self.client = client
        s = settings or {}
        self.jacad = JacadClient(s.get("jacad_base_url", ""), s.get("jacad_api_key", ""))
        self.moodle = MoodleClient(s.get("moodle_url", ""), s.get("moodle_token", ""))

    async def test_connection(self, system: str) -> Dict[str, Any]:
        if system == "jacad":
            return await self.jacad.test_connection()
        if system == "moodle":
            return await self.moodle.test_connection()
        return {"connected": False, "message": f"Sistema desconhecido: {system}"}

    async def get_status(self) -> Dict[str, Any]:
        jacad = await self.jacad.test_connection()
        moodle = await self.moodle.test_connection()
        jacad["enabled"] = not self.jacad.use_mock
        jacad["last_sync"] = None
        moodle["enabled"] = not self.moodle.use_mock
        moodle["last_sync"] = None
        return {"jacad": jacad, "moodle": moodle}

    # ---- JACAD sync ----

    async def sync_users_from_jacad(self, filters: Optional[Dict] = None) -> SyncResult:
        started = datetime.now(timezone.utc)
        result = SyncResult(
            system="jacad", operation="sync_users", direction="import",
            status="success", records_processed=0, started_at=started,
        )
        try:
            from auth import hash_password
            disciplines = await self.jacad.get_disciplines()
            all_students: List[Dict] = []
            for disc in disciplines:
                students = await self.jacad.get_discipline_students(disc.get("codigo", ""))
                all_students.extend(students)

            seen_ra = set()
            for s in all_students:
                ra = s.get("ra")
                if not ra or ra in seen_ra:
                    continue
                seen_ra.add(ra)
                result.records_processed += 1
                try:
                    existing = self.client.table("users").select("*").eq("ra", ra).maybe_single().execute()
                    if existing.data:
                        self.client.table("users").update({
                            "name": s.get("name", existing.data.get("name", "")),
                            "email": s.get("email", existing.data.get("email", "")),
                        }).eq("ra", ra).execute()
                        result.records_updated += 1
                    else:
                        self.client.table("users").insert({
                            "ra": ra,
                            "name": s.get("name", ""),
                            "email": s.get("email"),
                            "role": "STUDENT",
                            "password_hash": hash_password(ra),
                        }).execute()
                        result.records_created += 1
                except Exception as e:
                    result.records_failed += 1
                    logger.warning(f"Failed to upsert student {ra}: {e}")

        except Exception as e:
            result.status = "failed"
            result.error_message = str(e)

        result.completed_at = datetime.now(timezone.utc)
        await self._log_sync(result)
        return result

    async def sync_disciplines_from_jacad(self) -> SyncResult:
        started = datetime.now(timezone.utc)
        result = SyncResult(
            system="jacad", operation="sync_disciplines", direction="import",
            status="success", records_processed=0, started_at=started,
        )
        try:
            disciplines = await self.jacad.get_disciplines()
            for d in disciplines:
                result.records_processed += 1
                code = d.get("codigo", "")
                existing = self.client.table("disciplines").select("*").eq("code", code).maybe_single().execute()
                if existing.data:
                    self.client.table("disciplines").update({
                        "name": d.get("name", existing.data.get("name", "")),
                    }).eq("code", code).execute()
                    result.records_updated += 1
                else:
                    self.client.table("disciplines").insert({
                        "name": d.get("name", ""),
                        "code": code,
                        "department": d.get("department"),
                    }).execute()
                    result.records_created += 1
        except Exception as e:
            result.status = "failed"
            result.error_message = str(e)

        result.completed_at = datetime.now(timezone.utc)
        await self._log_sync(result)
        return result

    async def get_jacad_student(self, ra: str) -> Optional[Dict[str, Any]]:
        student = await self.jacad.get_student_by_ra(ra)
        if student:
            student["enrollments"] = await self.jacad.get_student_enrollments(ra)
        return student

    # ---- Moodle export ----

    async def export_sessions_to_moodle(self, filters: Optional[Dict] = None) -> SyncResult:
        started = datetime.now(timezone.utc)
        result = SyncResult(
            system="moodle", operation="export_sessions", direction="export",
            status="success", records_processed=0, started_at=started,
        )
        try:
            query = self.client.table("chat_sessions").select("*").is_("moodle_export_id", "null")
            if filters:
                if filters.get("user_id"):
                    query = query.eq("user_id", filters["user_id"])
            response = query.execute()
            sessions = response.data or []

            for session in sessions:
                result.records_processed += 1
                try:
                    export_id = f"HARVEN-MOODLE-{uuid4().hex[:8]}"
                    self.client.table("chat_sessions").update({
                        "moodle_export_id": export_id,
                    }).eq("id", session["id"]).execute()
                    result.records_created += 1
                except Exception:
                    result.records_failed += 1

        except Exception as e:
            result.status = "failed"
            result.error_message = str(e)

        result.completed_at = datetime.now(timezone.utc)
        await self._log_sync(result)
        return result

    async def import_ratings_from_moodle(self) -> SyncResult:
        started = datetime.now(timezone.utc)
        result = SyncResult(
            system="moodle", operation="import_ratings", direction="import",
            status="success", records_processed=0, started_at=started,
        )
        result.completed_at = datetime.now(timezone.utc)
        await self._log_sync(result)
        return result

    async def import_users_from_moodle(self, criteria: Optional[Dict] = None) -> SyncResult:
        """Import users from Moodle into Harven users table via UserRepository."""
        from auth import hash_password
        from repositories import UserRepository

        started = datetime.now(timezone.utc)
        result = SyncResult(
            system="moodle", operation="import_users", direction="import",
            status="success", records_processed=0, started_at=started,
        )

        user_repo = UserRepository(self.client)

        try:
            moodle_users = await self.moodle.get_users(criteria)
            # Moodle core_user_get_users can return either a list or {"users": [...]}
            if isinstance(moodle_users, dict):
                moodle_users = moodle_users.get("users", []) or []

            for mu in moodle_users:
                result.records_processed += 1
                ra = mu.get("idnumber") or mu.get("username") or (str(mu.get("id")) if mu.get("id") else None)
                if not ra:
                    result.records_failed += 1
                    continue

                name = mu.get("fullname") or (
                    f"{mu.get('firstname', '')} {mu.get('lastname', '')}".strip() or ra
                )
                email = mu.get("email")
                moodle_user_id = str(mu.get("id")) if mu.get("id") is not None else None

                try:
                    existing = user_repo.get_by_ra(ra)
                    if existing:
                        update_data = {"name": name}
                        if email:
                            update_data["email"] = email
                        if moodle_user_id:
                            update_data["moodle_user_id"] = moodle_user_id
                        user_repo.update(existing["id"], update_data)
                        result.records_updated += 1
                    else:
                        user_repo.create({
                            "ra": ra,
                            "name": name,
                            "email": email,
                            "role": "STUDENT",
                            "password_hash": hash_password(ra),
                            "moodle_user_id": moodle_user_id,
                        })
                        result.records_created += 1
                except Exception as e:
                    result.records_failed += 1
                    logger.warning(f"Failed to upsert moodle user {ra}: {e}")

        except Exception as e:
            result.status = "failed"
            result.error_message = str(e)

        result.completed_at = datetime.now(timezone.utc)
        await self._log_sync(result)
        return result

    async def get_moodle_ratings(self, filters: Optional[Dict] = None) -> List[Dict]:
        query = self.client.table("moodle_ratings").select("*")
        if filters:
            if filters.get("session_id"):
                query = query.eq("session_id", filters["session_id"])
        response = query.execute()
        rows = response.data or []
        return [
            {
                "id": r.get("id"), "session_id": r.get("session_id"), "student_id": r.get("student_id"),
                "teacher_id": r.get("teacher_id"), "rating": r.get("rating"), "feedback": r.get("feedback"),
                "rated_at": r.get("rated_at"),
            }
            for r in rows
        ]

    # ---- Webhooks ----

    async def handle_moodle_webhook(self, event_type: str, payload: Dict) -> Dict[str, Any]:
        if event_type == "rating_submitted":
            return await self._handle_rating_submitted(payload)
        if event_type == "grade_updated":
            return {"status": "acknowledged", "event": event_type}
        return {"status": "unknown_event", "event": event_type}

    async def _handle_rating_submitted(self, payload: Dict) -> Dict[str, Any]:
        try:
            self.client.table("moodle_ratings").insert({
                "session_id": payload.get("session_id"),
                "student_id": payload.get("student_id", ""),
                "teacher_id": payload.get("teacher_id", ""),
                "rating": payload.get("rating"),
                "feedback": payload.get("feedback"),
            }).execute()
        except Exception as e:
            logger.warning(f"Failed to insert moodle rating: {e}")
        return {"status": "processed", "event": "rating_submitted"}

    # ---- Logging ----

    async def _log_sync(self, sync_result: SyncResult) -> None:
        try:
            self.client.table("integration_logs").insert({
                "system": sync_result.system,
                "operation": sync_result.operation,
                "direction": sync_result.direction,
                "status": sync_result.status,
                "records_processed": sync_result.records_processed,
                "error_message": sync_result.error_message,
            }).execute()
        except Exception as e:
            logger.warning(f"Failed to log sync result: {e}")

    async def get_logs(self, filters: Optional[Dict] = None, limit: int = 50) -> List[Dict]:
        query = self.client.table("integration_logs").select("*").order("created_at", desc=True)
        if filters:
            if filters.get("system"):
                query = query.eq("system", filters["system"])
            if filters.get("status"):
                query = query.eq("status", filters["status"])
        query = query.limit(limit)
        response = query.execute()
        rows = response.data or []
        return [
            {
                "id": r.get("id"), "system": r.get("system"), "operation": r.get("operation"),
                "direction": r.get("direction"), "status": r.get("status"),
                "records_processed": r.get("records_processed"),
                "error_message": r.get("error_message"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ]

    # ---- Mappings ----

    async def get_mappings(self, entity_type: Optional[str] = None) -> List[Dict]:
        query = self.client.table("external_mappings").select("*")
        if entity_type:
            query = query.eq("entity_type", entity_type)
        response = query.execute()
        rows = response.data or []
        return [
            {
                "id": r.get("id"), "entity_type": r.get("entity_type"),
                "local_id": r.get("local_id"), "external_id": r.get("external_id"),
                "external_system": r.get("external_system"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ]


# ---------------------------------------------------------------------------
# LTI Service
# ---------------------------------------------------------------------------

LTI_NONCE_WINDOW = 300  # 5 minutes


class LTIValidationError(Exception):
    pass


@dataclass
class LTILaunchData:
    user_id: str
    ra: Optional[str] = None
    name: str = ""
    email: str = ""
    role: str = "STUDENT"
    context_id: Optional[str] = None
    context_title: Optional[str] = None
    resource_link_id: Optional[str] = None
    outcome_service_url: Optional[str] = None
    result_sourcedid: Optional[str] = None
    raw_params: Dict[str, str] = field(default_factory=dict)


ROLE_MAP = {
    "instructor": "TEACHER",
    "contentdeveloper": "TEACHER",
    "teachingassistant": "TEACHER",
    "administrator": "ADMIN",
    "learner": "STUDENT",
    "student": "STUDENT",
    "member": "STUDENT",
}


def _percent_encode(s: str) -> str:
    return urllib.parse.quote(str(s), safe="")


def _map_lti_roles(roles_str: str) -> str:
    if not roles_str:
        return "STUDENT"
    for part in roles_str.split(","):
        part = part.strip().lower()
        key = part.rsplit("/", 1)[-1] if "/" in part else part
        if key in ROLE_MAP:
            return ROLE_MAP[key]
    return "STUDENT"


def verify_oauth_signature(params: Dict[str, str], url: str, consumer_secret: str) -> bool:
    sig = params.get("oauth_signature", "")
    filtered = {k: v for k, v in params.items() if k != "oauth_signature"}

    sorted_params = sorted(filtered.items())
    encoded = "&".join(f"{_percent_encode(k)}={_percent_encode(v)}" for k, v in sorted_params)
    base_string = f"POST&{_percent_encode(url)}&{_percent_encode(encoded)}"

    signing_key = f"{_percent_encode(consumer_secret)}&"
    digest = hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, sig)


async def validate_lti_launch(
    form_params: Dict[str, str],
    url: str,
    consumer_key: str,
    consumer_secret: str,
) -> LTILaunchData:
    if form_params.get("lti_message_type") != "basic-lti-launch-request":
        raise LTIValidationError("Tipo de mensagem LTI invalido")

    version = form_params.get("lti_version", "")
    if version not in ("LTI-1p0", "LTI-1p1"):
        raise LTIValidationError(f"Versao LTI nao suportada: {version}")

    if form_params.get("oauth_consumer_key") != consumer_key:
        raise LTIValidationError("Consumer key invalido")

    ts = form_params.get("oauth_timestamp", "")
    try:
        ts_int = int(ts)
        now = int(datetime.now(timezone.utc).timestamp())
        if abs(now - ts_int) > LTI_NONCE_WINDOW:
            raise LTIValidationError("Timestamp expirado")
    except ValueError:
        raise LTIValidationError("Timestamp invalido")

    if not verify_oauth_signature(form_params, url, consumer_secret):
        raise LTIValidationError("Assinatura OAuth invalida")

    role = _map_lti_roles(form_params.get("roles", ""))

    return LTILaunchData(
        user_id=form_params.get("user_id", ""),
        ra=form_params.get("lis_person_sourcedid"),
        name=form_params.get("lis_person_name_full", ""),
        email=form_params.get("lis_person_contact_email_primary", ""),
        role=role,
        context_id=form_params.get("context_id"),
        context_title=form_params.get("context_title"),
        resource_link_id=form_params.get("resource_link_id"),
        outcome_service_url=form_params.get("lis_outcome_service_url"),
        result_sourcedid=form_params.get("lis_result_sourcedid"),
        raw_params=form_params,
    )


def generate_lti_config_xml(tool_name: str, launch_url: str, description: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cartridge_basiclti_link
    xmlns="http://www.imsglobal.org/xsd/imslticc_v1p0"
    xmlns:blti="http://www.imsglobal.org/xsd/imsbasiclti_v1p0"
    xmlns:lticm="http://www.imsglobal.org/xsd/imslticm_v1p0"
    xmlns:lticp="http://www.imsglobal.org/xsd/imslticp_v1p0"
    xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
    xsi:schemaLocation="http://www.imsglobal.org/xsd/imslticc_v1p0 http://www.imsglobal.org/xsd/lti/ltiv1p0/imslticc_v1p0.xsd
        http://www.imsglobal.org/xsd/imsbasiclti_v1p0 http://www.imsglobal.org/xsd/lti/ltiv1p0/imsbasiclti_v1p0p1.xsd
        http://www.imsglobal.org/xsd/imslticm_v1p0 http://www.imsglobal.org/xsd/lti/ltiv1p0/imslticm_v1p0.xsd
        http://www.imsglobal.org/xsd/imslticp_v1p0 http://www.imsglobal.org/xsd/lti/ltiv1p0/imslticp_v1p0.xsd">
    <blti:title>{tool_name}</blti:title>
    <blti:description>{description}</blti:description>
    <blti:launch_url>{launch_url}</blti:launch_url>
    <blti:extensions platform="moodle.org">
        <lticm:property name="privacy_level">public</lticm:property>
    </blti:extensions>
    <cartridge_bundle identifierref="BLTI001_Bundle"/>
    <cartridge_icon identifierref="BLTI001_Icon"/>
</cartridge_basiclti_link>"""
