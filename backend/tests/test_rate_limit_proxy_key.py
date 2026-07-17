"""P0 fix 3 — the rate-limit key must identify the STUDENT, not the proxy.

In production all traffic reaches uvicorn through a reverse proxy, so
``get_remote_address`` returned the proxy's IP for everyone — 5 failed logins by
ONE student exhausted the shared ``5/minute`` bucket and locked the whole school
out. ``_rate_limit_client_ip`` keys on the first ``X-Forwarded-For`` hop (the
origin client the proxy appends), falls back to ``X-Real-IP``, and finally to the
socket address so direct/dev access is unchanged.
"""
from __future__ import annotations

from types import SimpleNamespace


def _request(headers: dict | None = None, client_host: str = "10.0.0.9"):
    """Minimal stand-in exposing the two attributes the key function reads."""
    lowered = {k.lower(): v for k, v in (headers or {}).items()}

    class _Headers(dict):
        def get(self, key, default=None):  # header lookup is case-insensitive
            return lowered.get(key.lower(), default)

    return SimpleNamespace(headers=_Headers(), client=SimpleNamespace(host=client_host))


class TestRateLimitKey:
    def test_uses_first_xff_hop_behind_proxy(self):
        from main import _rate_limit_client_ip

        req = _request({"X-Forwarded-For": "203.0.113.7, 10.0.0.1"}, client_host="10.0.0.1")
        assert _rate_limit_client_ip(req) == "203.0.113.7"

    def test_single_xff_value(self):
        from main import _rate_limit_client_ip

        req = _request({"X-Forwarded-For": "198.51.100.42"})
        assert _rate_limit_client_ip(req) == "198.51.100.42"

    def test_falls_back_to_x_real_ip(self):
        from main import _rate_limit_client_ip

        req = _request({"X-Real-IP": "198.51.100.99"})
        assert _rate_limit_client_ip(req) == "198.51.100.99"

    def test_no_proxy_headers_uses_socket_address(self):
        from main import _rate_limit_client_ip

        req = _request({}, client_host="127.0.0.1")
        assert _rate_limit_client_ip(req) == "127.0.0.1"

    def test_empty_xff_does_not_collapse_key(self):
        """A blank header must not turn EVERY client into the same '' bucket."""
        from main import _rate_limit_client_ip

        req = _request({"X-Forwarded-For": "  "}, client_host="127.0.0.1")
        assert _rate_limit_client_ip(req) == "127.0.0.1"

    def test_two_students_behind_same_proxy_get_distinct_keys(self):
        from main import _rate_limit_client_ip

        a = _request({"X-Forwarded-For": "203.0.113.7, 10.0.0.1"}, client_host="10.0.0.1")
        b = _request({"X-Forwarded-For": "203.0.113.8, 10.0.0.1"}, client_host="10.0.0.1")
        assert _rate_limit_client_ip(a) != _rate_limit_client_ip(b)

    def test_limiter_is_wired_to_the_proxy_aware_key(self):
        """The app limiter must actually use the new key function."""
        import main

        assert main.limiter._key_func is main._rate_limit_client_ip
