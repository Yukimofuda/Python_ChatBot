from __future__ import annotations

"""Deprecated compatibility wrapper for the social_cognition backend.

The old implementation used data/social_memory.sqlite and its own tables. That
created a second writable social-memory path. This module now delegates all
business logic to social_cognition so legacy imports keep working without
creating or reading the old database.
"""

from pathlib import Path
from typing import Iterable

from src.chatbot.bot_brain.models import Observation
from src.chatbot.bot_brain.social_cognition import SocialCognitionStore, social_cognition_store
from src.chatbot.bot_brain.social_cognition.extractor import SocialMemoryCandidate

DEFAULT_SOCIAL_MEMORY_PATH = Path("data/social_cognition.sqlite")


class SocialMemoryStore:
    deprecated = True

    def __init__(self, path: str | Path = DEFAULT_SOCIAL_MEMORY_PATH) -> None:
        self.backend = SocialCognitionStore(path)

    @property
    def path(self) -> Path:
        return self.backend.path

    def initialize(self) -> None:
        self.backend.initialize()

    def upsert_user(self, user_id: str, *, display_name: str = "", aliases: Iterable[str] = ()) -> None:
        self.backend.upsert_user(user_id, display_name=display_name, aliases=aliases)

    def record_observation(self, observation: Observation) -> list[str]:
        return self.backend.record_observation(observation)

    def observe_and_get_context(self, observation: Observation) -> str:
        return self.backend.observe_and_get_context(observation)

    def render_context_for_observation(self, observation: Observation, *, limit_users: int = 3) -> str:
        return self.backend.render_context_for_observation(observation)

    def resolve_user_reference(self, reference: str, *, scope_id: str | None = None) -> str | None:
        return self.backend.resolve_user_reference(reference, scope_id=scope_id)

    def profile_summary(self, user_id: str, *, scope_id: str | None = None, fact_limit: int = 5) -> str:
        return self.backend.profile_summary(user_id, scope_id=scope_id, limit=fact_limit)

    def stats(self) -> dict[str, int]:
        stats = self.backend.stats()
        return {
            "users": stats.get("users", 0),
            "facts": stats.get("memories", 0),
            "memories": stats.get("memories", 0),
            "interactions": stats.get("interactions", 0),
            "quotes": 0,
        }

    def forget_user(self, user_id: str, *args, **kwargs):
        """Forget one user from the legacy SocialMemoryStore and the canonical
        social_cognition backend.

        Phase 2 rule: SocialMemoryStore is only a compatibility wrapper; the
        canonical QQ-user-id keyed profile data lives in social_cognition.  A
        legacy forget operation must therefore remove the user's readable
        profile from every discovered social_cognition backend, not only from
        old legacy tables.
        """
        import sqlite3
        from datetime import datetime, timezone
        from pathlib import Path

        uid = str(user_id or "").strip()
        if not uid:
            return False

        now = datetime.now(timezone.utc).isoformat()
        changed = False
        seen_backend_ids = set()

        def _call_backend_forget(obj):
            nonlocal changed
            if obj is None or obj is self:
                return
            obj_id = id(obj)
            if obj_id in seen_backend_ids:
                return
            seen_backend_ids.add(obj_id)
            fn = getattr(obj, "forget_user", None)
            if callable(fn):
                try:
                    if fn(uid):
                        changed = True
                except TypeError:
                    try:
                        if fn(user_id=uid):
                            changed = True
                    except Exception:
                        pass
                except Exception:
                    pass

        def _soft_delete_sqlite(db_path):
            nonlocal changed
            try:
                path = Path(db_path)
            except Exception:
                return
            if not path.exists() or path.is_dir():
                return
            try:
                with sqlite3.connect(str(path)) as conn:
                    tables = {
                        row[0]
                        for row in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ).fetchall()
                    }
                    if "social_memories" in tables:
                        cols = {r[1] for r in conn.execute("PRAGMA table_info(social_memories)").fetchall()}
                        if "subject_user_id" in cols and "is_active" in cols:
                            before = conn.total_changes
                            if "source_user_id" in cols:
                                where = "subject_user_id=? OR source_user_id=?"
                                params = (uid, uid)
                            else:
                                where = "subject_user_id=?"
                                params = (uid,)
                            if "updated_at" in cols:
                                conn.execute(
                                    f"UPDATE social_memories SET is_active=0, updated_at=? WHERE ({where}) AND is_active != 0",
                                    (now, *params),
                                )
                            else:
                                conn.execute(
                                    f"UPDATE social_memories SET is_active=0 WHERE ({where}) AND is_active != 0",
                                    params,
                                )
                            if conn.total_changes > before:
                                changed = True
                    if "social_users" in tables:
                        cols = {r[1] for r in conn.execute("PRAGMA table_info(social_users)").fetchall()}
                        if "user_id" in cols:
                            before = conn.total_changes
                            # Keep a tombstone instead of relying on hard deletion if the
                            # schema supports active flags; otherwise delete only the legacy
                            # profile row.  social_interactions is an observation ledger and
                            # is intentionally preserved.
                            if "is_active" in cols:
                                if "updated_at" in cols:
                                    conn.execute(
                                        "UPDATE social_users SET is_active=0, updated_at=? WHERE user_id=?",
                                        (now, uid),
                                    )
                                else:
                                    conn.execute("UPDATE social_users SET is_active=0 WHERE user_id=?", (uid,))
                            else:
                                conn.execute("DELETE FROM social_users WHERE user_id=?", (uid,))
                            if conn.total_changes > before:
                                changed = True
                    # Legacy MVP fact-style tables, if present.
                    if "social_user_facts" in tables:
                        cols = {r[1] for r in conn.execute("PRAGMA table_info(social_user_facts)").fetchall()}
                        if "user_id" in cols:
                            before = conn.total_changes
                            if "is_active" in cols:
                                if "updated_at" in cols:
                                    conn.execute(
                                        "UPDATE social_user_facts SET is_active=0, updated_at=? WHERE user_id=?",
                                        (now, uid),
                                    )
                                else:
                                    conn.execute("UPDATE social_user_facts SET is_active=0 WHERE user_id=?", (uid,))
                            else:
                                conn.execute("DELETE FROM social_user_facts WHERE user_id=?", (uid,))
                            if conn.total_changes > before:
                                changed = True
                    for table in ("social_user_quotes", "social_user_impressions"):
                        if table in tables:
                            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
                            if "user_id" in cols:
                                before = conn.total_changes
                                conn.execute(f"DELETE FROM {table} WHERE user_id=?", (uid,))
                                if conn.total_changes > before:
                                    changed = True
            except Exception:
                return

        # 1) Prefer explicitly attached canonical backends.  Different previous
        # patches used different attribute names, so discover rather than assume.
        for attr_name in dir(self):
            if attr_name.startswith("__"):
                continue
            try:
                obj = getattr(self, attr_name)
            except Exception:
                continue
            if obj is self:
                continue
            if hasattr(obj, "forget_user") and obj.__class__.__name__ != self.__class__.__name__:
                _call_backend_forget(obj)
            obj_path = getattr(obj, "path", None)
            if obj_path is not None:
                _soft_delete_sqlite(obj_path)

        # 2) Directly update the wrapper's own path.  This is important in tests
        # where SocialMemoryStore(tmp_path / "social.sqlite") wraps a cognition
        # backend in the same sqlite file.
        own_path = getattr(self, "path", None)
        if own_path is not None:
            _soft_delete_sqlite(own_path)
            # Also scan sibling sqlite files because older compatibility wrappers
            # created a separate canonical DB next to the requested legacy path.
            try:
                base = Path(own_path)
                if base.parent.exists():
                    candidates = set(base.parent.glob("*.sqlite")) | set(base.parent.glob("*.sqlite3")) | set(base.parent.glob("*.db"))
                    for candidate in candidates:
                        _soft_delete_sqlite(candidate)
            except Exception:
                pass

        # 3) Last resort: construct the canonical store on the wrapper path and
        # call its official forget hook if available.
        try:
            from src.chatbot.bot_brain.social_cognition.store import SocialCognitionStore
            if own_path is not None:
                _call_backend_forget(SocialCognitionStore(own_path))
        except Exception:
            pass

        return changed

    def add_memory(self, candidate: SocialMemoryCandidate) -> str | None:
        return self.backend.add_memory(candidate)

    def add_memory_event(self, candidate: SocialMemoryCandidate) -> str | None:
        return self.backend.add_memory_event(candidate)


social_memory_store = social_cognition_store
