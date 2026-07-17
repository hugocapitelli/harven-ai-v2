"""P1 fix 7 — request-size limits coherent with what the UI promises.

The middleware cut EVERY upload at a flat 50MB while the admin UI advertises
500MB for video and 100MB for audio — real lecture uploads always died with 413.
Limits are now per upload type: 500MB ``/upload/video``, 100MB ``/upload/audio``,
50MB other uploads (avatar/image/generic), 10MB everything else.
"""
from __future__ import annotations

MB = 1024 * 1024


def _mw():
    from main import RequestSizeLimitMiddleware

    return RequestSizeLimitMiddleware(app=None)


class TestLimitSelection:
    def test_video_uploads_get_500mb(self):
        assert _mw()._limit_for("/upload/video") == 500 * MB

    def test_audio_uploads_get_100mb(self):
        assert _mw()._limit_for("/upload/audio") == 100 * MB

    def test_generic_upload_keeps_50mb(self):
        assert _mw()._limit_for("/upload") == 50 * MB

    def test_avatar_and_image_keep_50mb(self):
        assert _mw()._limit_for("/users/u1/avatar") == 50 * MB
        assert _mw()._limit_for("/disciplines/d1/image") == 50 * MB

    def test_non_upload_routes_keep_10mb(self):
        assert _mw()._limit_for("/auth/login") == 10 * MB


class TestEnforcementThroughApp:
    def test_video_route_accepts_body_over_50mb(self, client, as_teacher):
        """A 200MB Content-Length on /upload/video must NOT be rejected by the
        middleware anymore (it may fail later for other reasons, but never 413)."""
        resp = client.post(
            "/upload/video",
            headers={"Content-Length": str(200 * MB)},
        )
        assert resp.status_code != 413, resp.text

    def test_video_route_still_caps_at_500mb(self, client, as_teacher):
        resp = client.post(
            "/upload/video",
            headers={"Content-Length": str(501 * MB)},
        )
        assert resp.status_code == 413

    def test_audio_route_accepts_body_over_50mb(self, client, as_teacher):
        resp = client.post(
            "/upload/audio",
            headers={"Content-Length": str(90 * MB)},
        )
        assert resp.status_code != 413

    def test_audio_route_caps_at_100mb(self, client, as_teacher):
        resp = client.post(
            "/upload/audio",
            headers={"Content-Length": str(101 * MB)},
        )
        assert resp.status_code == 413

    def test_generic_upload_still_caps_at_50mb(self, client, as_teacher):
        resp = client.post(
            "/upload",
            headers={"Content-Length": str(51 * MB)},
        )
        assert resp.status_code == 413
