from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .base import Conversation, Turn, new_conversation_id

DEFAULT_RETENTION_COUNT = 200
# One pathological turn cannot blow out disk; the marker makes a truncated
# turn visibly distinct from one that just happened to end there.
MAX_TURN_TEXT_BYTES = 200_000
_TRUNCATION_MARKER = "\n…[truncated]"


def default_data_dir() -> Path:
    # XDG_DATA_HOME (not XDG_CACHE_HOME): transcripts are irreplaceable user
    # content, not disposable/regenerable cache. omarchy-everything, not a
    # shared omarchy/ namespace, matches the real sibling convention on this
    # machine (~/.local/share/omarchy-podcasts, ~/.local/share/omarchy-ytmusic
    # both exist; a shared ~/.local/share/omarchy/ does not).
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return Path(base) / "omarchy-everything" / "agent"


@dataclass(slots=True)
class ConversationSummary:
    id: str
    agent: str
    mode: str
    title: str
    created_at: float
    updated_at: float
    turn_count: int

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "agent": self.agent,
            "mode": self.mode,
            "title": self.title,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
            "turnCount": self.turn_count,
        }


def _safe_conversation_id(conversation_id: str) -> str:
    value = str(conversation_id or "")
    if not value or not all(ch.isalnum() for ch in value):
        raise ValueError("invalid conversation id")
    return value


class ConversationStore:
    """Owns the on-disk transcript cache. Never stores API keys/env vars, raw
    file contents an agent touched, or activation-token-style secrets — only
    role/text/timestamp turns plus each CLI's own local resumable session id
    (a session pointer, not a bearer credential), named explicitly here and
    in docs/security.md."""

    def __init__(self, root: Path | None = None, *, retention_count: int = DEFAULT_RETENTION_COUNT):
        self.root = root or default_data_dir()
        self.retention_count = max(1, int(retention_count))
        self.conversations_dir = self.root / "conversations"
        self.index_path = self.root / "index.json"
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.conversations_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        os.chmod(self.conversations_dir, 0o700)

    def _conversation_path(self, conversation_id: str) -> Path:
        return self.conversations_dir / f"{_safe_conversation_id(conversation_id)}.jsonl"

    def _read_index(self) -> list[dict]:
        try:
            raw = self.index_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return [entry for entry in value if isinstance(entry, dict)] if isinstance(value, list) else []

    def _write_index(self, entries: list[dict]) -> None:
        tmp_path = self.index_path.with_name(self.index_path.name + ".tmp")
        tmp_path.write_text(json.dumps(entries), encoding="utf-8")
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, self.index_path)

    def list_conversations(self) -> list[ConversationSummary]:
        summaries = [
            ConversationSummary(
                id=str(entry.get("id") or ""),
                agent=str(entry.get("agent") or ""),
                mode=str(entry.get("mode") or ""),
                title=str(entry.get("title") or "New conversation"),
                created_at=float(entry.get("createdAt") or 0),
                updated_at=float(entry.get("updatedAt") or 0),
                turn_count=int(entry.get("turnCount") or 0),
            )
            for entry in self._read_index()
        ]
        summaries.sort(key=lambda summary: summary.updated_at, reverse=True)
        return summaries

    def create(self, agent: str, mode: str, allowed_dirs: tuple[str, ...]) -> Conversation:
        conversation_id = new_conversation_id()
        now = time.time()
        conversation = Conversation(
            id=conversation_id,
            agent=agent,
            mode=mode,
            allowed_dirs=tuple(allowed_dirs),
            created_at=now,
            updated_at=now,
        )
        path = self._conversation_path(conversation_id)
        path.touch()
        os.chmod(path, 0o600)
        entries = self._read_index()
        entries.append({
            "id": conversation.id,
            "agent": conversation.agent,
            "mode": conversation.mode,
            "title": conversation.title,
            "createdAt": conversation.created_at,
            "updatedAt": conversation.updated_at,
            "turnCount": 0,
            "allowedDirs": list(conversation.allowed_dirs),
            "providerSessionId": "",
        })
        self._write_index(entries)
        self._enforce_retention()
        return conversation

    def append_turn(self, conversation_id: str, turn: Turn) -> None:
        path = self._conversation_path(conversation_id)
        text = turn.text
        if len(text.encode("utf-8")) > MAX_TURN_TEXT_BYTES:
            text = text.encode("utf-8")[:MAX_TURN_TEXT_BYTES].decode("utf-8", "ignore") + _TRUNCATION_MARKER
        bounded = Turn(role=turn.role, text=text, at=turn.at)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(bounded.to_json(), ensure_ascii=False) + "\n")
        os.chmod(path, 0o600)

        entries = self._read_index()
        for entry in entries:
            if entry.get("id") == conversation_id:
                entry["updatedAt"] = bounded.at
                entry["turnCount"] = int(entry.get("turnCount") or 0) + 1
                current_title = entry.get("title")
                if bounded.role == "user" and current_title in (None, "", "New conversation") and text.strip():
                    entry["title"] = text.strip().splitlines()[0][:120]
        self._write_index(entries)

    def set_provider_session_id(self, conversation_id: str, provider_session_id: str) -> None:
        if not provider_session_id:
            return
        entries = self._read_index()
        for entry in entries:
            if entry.get("id") == conversation_id:
                entry["providerSessionId"] = provider_session_id
        self._write_index(entries)

    def get(self, conversation_id: str) -> Conversation | None:
        meta = next((entry for entry in self._read_index() if entry.get("id") == conversation_id), None)
        if not meta:
            return None
        turns: list[Turn] = []
        try:
            with self._conversation_path(conversation_id).open("r", encoding="utf-8") as handle:
                for raw_line in handle:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        value = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # a crash mid-append leaves one discardable partial line
                    turn = Turn.from_json(value) if isinstance(value, dict) else None
                    if turn is not None:
                        turns.append(turn)
        except (FileNotFoundError, ValueError):
            pass
        return Conversation(
            id=conversation_id,
            agent=str(meta.get("agent") or ""),
            mode=str(meta.get("mode") or ""),
            allowed_dirs=tuple(meta.get("allowedDirs") or ()),
            created_at=float(meta.get("createdAt") or 0),
            updated_at=float(meta.get("updatedAt") or 0),
            turns=turns,
            provider_session_id=str(meta.get("providerSessionId") or ""),
        )

    def delete(self, conversation_id: str) -> bool:
        entries = self._read_index()
        remaining = [entry for entry in entries if entry.get("id") != conversation_id]
        found = len(remaining) != len(entries)
        self._write_index(remaining)
        try:
            self._conversation_path(conversation_id).unlink()
        except (FileNotFoundError, ValueError):
            pass
        return found

    def _enforce_retention(self) -> None:
        entries = self._read_index()
        if len(entries) <= self.retention_count:
            return
        entries.sort(key=lambda entry: entry.get("updatedAt") or 0, reverse=True)
        keep, drop = entries[: self.retention_count], entries[self.retention_count:]
        for entry in drop:
            try:
                self._conversation_path(str(entry.get("id") or "")).unlink()
            except (FileNotFoundError, ValueError):
                pass
        self._write_index(keep)
