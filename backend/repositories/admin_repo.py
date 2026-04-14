"""Admin repository — Supabase client API."""
from typing import Dict, List, Optional, Tuple
from supabase import Client


class AdminRepository:
    def __init__(self, client: Client):
        self.client = client

    # ── Settings (singleton) ─────────────────────────────

    def get_settings(self) -> Optional[Dict]:
        res = self.client.table("system_settings").select("*").limit(1).maybe_single().execute()
        return res.data

    def save_settings(self, data: dict) -> Dict:
        existing = self.get_settings()
        if existing:
            # Preserve URL fields when new value is empty
            url_fields = [k for k in data if k.endswith("_url") or k.endswith("_logo") or k.endswith("_bg")]
            for field in url_fields:
                if not data[field] and existing.get(field):
                    data.pop(field)
            res = self.client.table("system_settings").update(data).eq("id", existing["id"]).execute()
            return res.data[0] if res.data else existing
        else:
            res = self.client.table("system_settings").insert(data).execute()
            return res.data[0] if res.data else {}

    # ── Logs ─────────────────────────────────────────────

    def get_logs(self, skip: int = 0, limit: int = 50, search: str = None, log_type: str = None) -> Tuple[List[Dict], int]:
        q = self.client.table("system_logs").select("*", count="exact")
        if search:
            q = q.or_(f"message.ilike.%{search}%,author.ilike.%{search}%")
        if log_type:
            q = q.eq("log_type", log_type)
        q = q.order("created_at", desc=True).range(skip, skip + limit - 1)
        res = q.execute()
        return res.data or [], res.count or 0

    def create_log(self, data: dict) -> Dict:
        res = self.client.table("system_logs").insert(data).execute()
        return res.data[0] if res.data else {}

    # ── Backups ──────────────────────────────────────────

    def get_backups(self) -> List[Dict]:
        res = self.client.table("system_backups").select("*").order("created_at", desc=True).execute()
        return res.data or []

    def create_backup(self, data: dict) -> Dict:
        res = self.client.table("system_backups").insert(data).execute()
        return res.data[0] if res.data else {}

    def get_backup_by_id(self, backup_id: str) -> Optional[Dict]:
        res = self.client.table("system_backups").select("*").eq("id", backup_id).maybe_single().execute()
        return res.data

    def delete_backup(self, backup_id: str) -> bool:
        res = self.client.table("system_backups").delete().eq("id", backup_id).execute()
        return bool(res.data)
