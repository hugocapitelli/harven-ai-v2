"""Security test package (EPIC-SEC).

The Foundation ``conftest.py`` puts ``backend/`` and ``backend/tests/`` on
``sys.path`` so modules like ``conftest`` / ``fakes`` / ``idor_helpers`` import as
top-level. SEC-ADMIN-6 adds a sibling helper (``scope_registry``) that lives in
THIS package directory; expose it as a top-level import too, so the guard tests can
do ``from scope_registry import ...`` regardless of pytest's import mode — without
editing the shared ``conftest.py``.
"""
import os
import sys

_SECURITY_DIR = os.path.dirname(os.path.abspath(__file__))
if _SECURITY_DIR not in sys.path:
    sys.path.insert(0, _SECURITY_DIR)
