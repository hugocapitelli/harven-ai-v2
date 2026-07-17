"""P2 fix 11 — upload endpoints are staff-only.

``POST /upload`` (and its /video, /audio siblings) accepted ANY authenticated
user, letting a student park arbitrary allowed-type files on the server's public
``/uploads`` mount. Uploading content is an authoring capability: now gated by
``require_role("ADMIN", "TEACHER", "INSTRUCTOR")``. Type validation is preserved
(storage-service whitelist for /upload; extension whitelist for video/audio).
"""
from __future__ import annotations

import io


def _file(name="doc.txt", content=b"hello", mime="text/plain"):
    return {"file": (name, io.BytesIO(content), mime)}


class TestStudentIsRejected:
    def test_generic_upload_403(self, client, as_student):
        resp = client.post("/upload", files=_file())
        assert resp.status_code == 403, resp.text

    def test_video_upload_403(self, client, as_student):
        resp = client.post("/upload/video", files=_file("aula.mp4", b"x", "video/mp4"))
        assert resp.status_code == 403, resp.text

    def test_audio_upload_403(self, client, as_student):
        resp = client.post("/upload/audio", files=_file("aula.mp3", b"x", "audio/mpeg"))
        assert resp.status_code == 403, resp.text


class TestStaffStillUploads:
    def test_teacher_generic_upload_not_403(self, client, as_teacher):
        resp = client.post("/upload", files=_file())
        # May 400/500 depending on the storage backend in tests — the gate itself
        # must not reject a teacher.
        assert resp.status_code != 403, resp.text

    def test_admin_generic_upload_not_403(self, client, as_admin):
        resp = client.post("/upload", files=_file())
        assert resp.status_code != 403, resp.text


class TestTypeValidationPreserved:
    def test_video_bad_extension_is_400_for_staff(self, client, as_teacher):
        resp = client.post("/upload/video", files=_file("malware.exe", b"x", "application/x-msdownload"))
        assert resp.status_code == 400, resp.text

    def test_audio_bad_extension_is_400_for_staff(self, client, as_teacher):
        resp = client.post("/upload/audio", files=_file("script.sh", b"x", "text/x-sh"))
        assert resp.status_code == 400, resp.text
