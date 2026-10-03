"""JSON-backed store for Mind definitions."""

from __future__ import annotations

import json
import time
from pathlib import Path

from learnage.minds.base import Mind


# Sort modes for the sidebar
SORT_MANUAL = "manual"     # user-defined order via position
SORT_NAME = "name"         # alphabetical
SORT_RECENT = "recent"     # last opened first
SORT_POPULAR = "popular"   # most-used first
SORT_BUILTIN = "builtin"   # built-ins first, then user alphabetical (default)

ALL_SORTS = [SORT_BUILTIN, SORT_MANUAL, SORT_NAME, SORT_RECENT, SORT_POPULAR]
SORT_LABELS = {
    SORT_MANUAL: "Manual order",
    SORT_NAME: "Name",
    SORT_RECENT: "Recently used",
    SORT_POPULAR: "Most used",
    SORT_BUILTIN: "Built-ins first",
}


class MindsStore:
    """Persists Mind definitions to ~/.learnage/minds.json.

    Built-in minds are re-seeded on every load so user edits to them are
    lost — by design. Custom minds are kept verbatim.
    """

    def __init__(self, home: Path) -> None:
        self.home = Path(home)
        self.path = self.home / "minds.json"
        self._minds: dict[str, Mind] = {}
        self._settings: dict = {}
        self._load()

    # ----------------------------------------------------------- persistence

    def _load(self) -> None:
        # Seed built-ins first
        from learnage.minds.builtin import builtin_minds
        builtins = list(builtin_minds())
        # Ensure built-ins have predictable positions (0..N-1)
        for i, m in enumerate(builtins):
            m.position = i
        self._minds = {m.id: m for m in builtins}

        # Then overlay user minds + settings from disk
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._settings = data.get("settings", {}) or {}
                    user_list = data.get("minds", [])
                elif isinstance(data, list):
                    # Backward compat — old format was a bare list
                    user_list = data
                    self._settings = {}
                else:
                    user_list = []
                for entry in user_list:
                    if not isinstance(entry, dict):
                        continue
                    m = Mind.from_dict(entry)
                    # Built-ins are immutable — keep the seeded version
                    if m.id in self._minds:
                        continue
                    self._minds[m.id] = m
            except Exception:  # noqa: BLE001
                # Corrupt file — back it up and keep only built-ins
                try:
                    bak = self.path.with_suffix(".json.bak")
                    self.path.replace(bak)
                except Exception:  # noqa: BLE001
                    pass
                self._settings = {}

        # Default sort if unset
        if "sort" not in self._settings:
            self._settings["sort"] = SORT_BUILTIN

    def _save(self) -> None:
        user_minds = [m.to_dict() for m in self._minds.values() if not m.is_builtin]
        payload = {
            "settings": self._settings,
            "minds": user_minds,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self.path)

    # ------------------------------------------------------------- queries

    def list_all(self) -> list[Mind]:
        return self._sorted()

    def _sorted(self) -> list[Mind]:
        mode = self._settings.get("sort", SORT_BUILTIN)
        minds = list(self._minds.values())
        if mode == SORT_MANUAL:
            # built-ins first by position, then user minds by position
            minds.sort(key=lambda m: (not m.is_builtin, m.position, m.name.lower()))
        elif mode == SORT_NAME:
            minds.sort(key=lambda m: (not m.is_builtin, m.name.lower()))
        elif mode == SORT_RECENT:
            minds.sort(key=lambda m: (
                not m.is_builtin,
                -(time.mktime(time.strptime(m.last_opened_at, "%Y-%m-%dT%H:%M:%S")))
                  if m.last_opened_at else 0,
                m.name.lower(),
            ))
        elif mode == SORT_POPULAR:
            minds.sort(key=lambda m: (
                not m.is_builtin,
                -m.session_count,
                m.name.lower(),
            ))
        else:  # SORT_BUILTIN
            minds.sort(key=lambda m: (not m.is_builtin, m.name.lower()))
        return minds

    def list_custom(self) -> list[Mind]:
        return [m for m in self._minds.values() if not m.is_builtin]

    def list_builtin(self) -> list[Mind]:
        return [m for m in self._minds.values() if m.is_builtin]

    def get(self, mind_id: str) -> Mind | None:
        return self._minds.get(mind_id)

    def sort_mode(self) -> str:
        return self._settings.get("sort", SORT_BUILTIN)

    def set_sort_mode(self, mode: str) -> None:
        if mode not in ALL_SORTS:
            raise ValueError(f"unknown sort mode: {mode}")
        self._settings["sort"] = mode
        self._save()

    # ------------------------------------------------------------ mutators

    def add(self, mind: Mind) -> None:
        mind.created_at = mind.created_at or time.strftime("%Y-%m-%dT%H:%M:%S")
        mind.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        mind.is_builtin = False
        # Assign a position at the end of the user-mind list
        user_positions = [m.position for m in self._minds.values() if not m.is_builtin]
        mind.position = (max(user_positions) + 1) if user_positions else 0
        self._minds[mind.id] = mind
        self._save()

    def update(self, mind: Mind) -> None:
        if mind.id not in self._minds:
            raise KeyError(f"unknown mind: {mind.id}")
        mind.updated_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        mind.is_builtin = self._minds[mind.id].is_builtin  # don't change
        self._minds[mind.id] = mind
        if not mind.is_builtin:
            self._save()

    def delete(self, mind_id: str) -> None:
        m = self._minds.get(mind_id)
        if not m:
            return
        if m.is_builtin:
            raise ValueError("cannot delete built-in mind")
        del self._minds[mind_id]
        self._save()

    def duplicate(self, mind_id: str, new_id: str, new_name: str) -> Mind | None:
        src = self._minds.get(mind_id)
        if not src:
            return None
        copy = Mind.from_dict(src.to_dict())
        copy.id = new_id
        copy.name = new_name
        copy.is_builtin = False
        copy.session_count = 0
        copy.last_opened_at = ""
        copy.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        copy.updated_at = copy.created_at
        # Place right after the source mind
        user_positions = [m.position for m in self._minds.values() if not m.is_builtin]
        copy.position = (max(user_positions) + 1) if user_positions else 0
        self._minds[copy.id] = copy
        self._save()
        return copy

    # --------------------------------------------------------- reorder + use

    def move_up(self, mind_id: str) -> bool:
        return self._reorder(mind_id, delta=-1)

    def move_down(self, mind_id: str) -> bool:
        return self._reorder(mind_id, delta=+1)

    def _reorder(self, mind_id: str, delta: int) -> bool:
        m = self._minds.get(mind_id)
        if not m or m.is_builtin:
            return False
        # Build current user list in position order
        user_minds = sorted(
            [x for x in self._minds.values() if not x.is_builtin],
            key=lambda x: x.position,
        )
        ids = [x.id for x in user_minds]
        if mind_id not in ids:
            return False
        idx = ids.index(mind_id)
        new_idx = idx + delta
        if new_idx < 0 or new_idx >= len(ids):
            return False
        ids[idx], ids[new_idx] = ids[new_idx], ids[idx]
        # Re-assign positions
        for pos, mid in enumerate(ids):
            self._minds[mid].position = pos
        self._save()
        return True

    def reorder(self, ordered_ids: list[str]) -> None:
        """Set user-mind order explicitly (from drag-drop)."""
        valid = {mid for mid in ordered_ids
                 if mid in self._minds and not self._minds[mid].is_builtin}
        for pos, mid in enumerate(ordered_ids):
            if mid in valid:
                self._minds[mid].position = pos
        # Any user minds missing from the list go to the end
        leftover = [m for m in self._minds.values()
                    if not m.is_builtin and m.id not in valid]
        base = max((self._minds[mid].position for mid in valid), default=-1) + 1
        for i, m in enumerate(leftover):
            m.position = base + i
        self._save()

    def record_open(self, mind_id: str) -> None:
        m = self._minds.get(mind_id)
        if not m:
            return
        m.session_count += 1
        m.last_opened_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        if not m.is_builtin:
            self._save()
