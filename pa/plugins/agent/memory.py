from __future__ import annotations
import datetime
from typing import Any
from pa.core.store import Store


class AgentMemory:
    def __init__(self, store: Store):
        self._store = store

    async def log_iteration(
        self,
        run_id: str,
        iteration: int,
        build_status: str,
        screenshot_desc: str,
        what_happened: str,
        files_changed: str,
        succeeded: bool,
    ) -> None:
        await self._store.execute(
            """INSERT INTO agent_iterations
               (run_id, iteration, build_status, screenshot_desc,
                what_happened, files_changed, succeeded)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_id, iteration, build_status, screenshot_desc,
             what_happened, files_changed, int(succeeded)),
        )

    async def save_fix(
        self,
        error_signature: str,
        fix_that_worked: str,
        file_affected: str,
    ) -> None:
        await self._store.execute(
            """INSERT INTO agent_fixes
               (error_signature, fix_that_worked, file_affected, last_used)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(error_signature) DO UPDATE SET
               fix_that_worked=excluded.fix_that_worked,
               times_applied=times_applied+1,
               last_used=excluded.last_used""",
            (error_signature, fix_that_worked, file_affected,
             datetime.datetime.now().isoformat()),
        )

    async def get_fix(self, error_signature: str) -> dict | None:
        return await self._store.fetchone(
            "SELECT * FROM agent_fixes WHERE error_signature = ?",
            (error_signature,),
        )

    async def add_lesson(self, lesson: str, source: str = "agent") -> None:
        await self._store.execute(
            "INSERT INTO agent_lessons (lesson, source) VALUES (?, ?)",
            (lesson, source),
        )

    async def get_all_lessons(self) -> list[dict]:
        return await self._store.fetchall(
            "SELECT lesson, source, learned_at FROM agent_lessons ORDER BY id DESC LIMIT 50"
        )

    async def set_game_state(self, key: str, value: str) -> None:
        await self._store.execute(
            """INSERT INTO agent_game_state (key, value, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
               value=excluded.value, updated_at=excluded.updated_at""",
            (key, value, datetime.datetime.now().isoformat()),
        )

    async def get_game_state(self, key: str) -> str | None:
        row = await self._store.fetchone(
            "SELECT value FROM agent_game_state WHERE key = ?", (key,)
        )
        return row["value"] if row else None

    async def update_screen_status(
        self,
        screen_name: str,
        file_path: str,
        working: bool,
        notes: str = "",
    ) -> None:
        now = datetime.datetime.now().isoformat()
        if working:
            await self._store.execute(
                """INSERT INTO agent_screen_status
                   (screen_name, file_path, last_confirmed_working, notes)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(screen_name) DO UPDATE SET
                   last_confirmed_working=excluded.last_confirmed_working,
                   file_path=excluded.file_path,
                   notes=excluded.notes""",
                (screen_name, file_path, now, notes),
            )
        else:
            await self._store.execute(
                """INSERT INTO agent_screen_status
                   (screen_name, file_path, last_broke, notes)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(screen_name) DO UPDATE SET
                   last_broke=excluded.last_broke,
                   notes=excluded.notes""",
                (screen_name, file_path, now, notes),
            )

    async def get_last_iterations(self, n: int = 10) -> list[dict]:
        return await self._store.fetchall(
            """SELECT * FROM agent_iterations
               ORDER BY id DESC LIMIT ?""",
            (n,),
        )

    async def get_status_summary(self) -> str:
        last = await self._store.fetchone(
            "SELECT * FROM agent_iterations ORDER BY id DESC LIMIT 1"
        )
        lessons = await self.get_all_lessons()
        screens = await self._store.fetchall(
            "SELECT * FROM agent_screen_status ORDER BY screen_name"
        )
        working = [s for s in screens if s.get("last_confirmed_working")]
        broken  = [s for s in screens if s.get("last_broke") and not s.get("last_confirmed_working")]

        lines = ["**DungeonMind Agent Status**\n"]
        if last:
            lines.append(f"Last run: iteration {last['iteration']} — Build: {last['build_status']}")
            lines.append(f"What happened: {last['what_happened'][:200]}")
        else:
            lines.append("No runs recorded yet.")

        lines.append(f"\nScreens working: {len(working)}")
        lines.append(f"Screens broken: {len(broken)}")
        if broken:
            lines.append("Broken: " + ", ".join(s["screen_name"] for s in broken))

        lines.append(f"\nLessons learned: {len(lessons)}")
        if lessons:
            lines.append("Latest: " + lessons[0]["lesson"][:100])

        return "\n".join(lines)
