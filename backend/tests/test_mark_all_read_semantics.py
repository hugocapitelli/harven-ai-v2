"""P2 fix 9 — ``PUT /notifications/{user_id}/read-all`` response semantics.

The old handler counted the rows REMAINING unread after the update but stored it
in a variable named ``marked`` and returned ``{"marked_read": "all",
"remaining_unread": <that count>}`` — so ``marked_read`` was a literal string and
``remaining_unread`` was measured at the wrong moment to mean anything. Now
``marked_read`` is how many rows were actually flipped and ``remaining_unread``
is the (post-update) leftover, normally 0.
"""
from __future__ import annotations

from conftest import STUDENT_A_ID


def _seed_unread(fake, n: int):
    for i in range(n):
        fake.add("notifications", {
            "id": f"unread-{i}", "user_id": STUDENT_A_ID,
            "title": f"N{i}", "is_read": False,
        })


class TestMarkAllReadSemantics:
    def test_counts_are_real_numbers(self, client, as_student, fake_supabase):
        _seed_unread(fake_supabase, 3)
        resp = client.put(f"/notifications/{STUDENT_A_ID}/read-all")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["marked_read"] == 3
        assert body["remaining_unread"] == 0

    def test_no_unread_marks_zero(self, client, as_student, fake_supabase):
        resp = client.put(f"/notifications/{STUDENT_A_ID}/read-all")
        body = resp.json()
        assert body["marked_read"] == 0
        assert body["remaining_unread"] == 0

    def test_rows_actually_flipped(self, client, as_student, fake_supabase):
        _seed_unread(fake_supabase, 2)
        client.put(f"/notifications/{STUDENT_A_ID}/read-all")
        unread = [
            r for r in fake_supabase.rows("notifications")
            if r["user_id"] == STUDENT_A_ID and r.get("is_read") is False
        ]
        assert unread == []
