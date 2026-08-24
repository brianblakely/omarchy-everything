from __future__ import annotations

import shutil
import time
import uuid
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Sequence

MODE_ASK = "ask"
MODE_PLAN = "plan"
MODE_RUN = "run"
MODES = (MODE_ASK, MODE_PLAN, MODE_RUN)

# Bounds shared by every adapter. An agent call is not a local scan: it is
# genuinely long-running and networked, so these are minutes, not the
# discovery helper's sub-second CommandRunner default.
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_IDLE_TIMEOUT_SECONDS = 90.0

# Flags no adapter may ever emit for MODE_RUN or MODE_PLAN. This subsystem's
# entire safety story is "never the bypass-permissions terminal wrapper";
# tests assert this list is honored by every registered adapter.
FORBIDDEN_RUN_FLAGS = (
    "--dangerously-skip-permissions",
    "--allow-dangerously-skip-permissions",
    "--dangerously-bypass-approvals-and-sandbox",
    "--yolo",
    "-y",
    "--auto",
)


def new_conversation_id() -> str:
    return uuid.uuid4().hex


@dataclass(slots=True)
class AgentRequest:
    agent: str
    mode: str
    prompt: str
    allowed_dirs: tuple[str, ...] = ()
    resume_session_id: str = ""
    conversation_id: str = ""


@dataclass(slots=True)
class Turn:
    role: str  # "user" | "assistant" | "system"
    text: str
    at: float = field(default_factory=time.time)

    def to_json(self) -> dict[str, object]:
        return {"role": self.role, "text": self.text, "at": self.at}

    @staticmethod
    def from_json(value: dict[str, object]) -> "Turn | None":
        role = str(value.get("role") or "")
        text = value.get("text")
        if role not in ("user", "assistant", "system") or not isinstance(text, str):
            return None
        at = value.get("at")
        return Turn(role=role, text=text, at=float(at) if isinstance(at, (int, float)) else time.time())


@dataclass(slots=True)
class Conversation:
    id: str
    agent: str
    mode: str
    allowed_dirs: tuple[str, ...]
    created_at: float
    updated_at: float
    turns: list[Turn] = field(default_factory=list)
    provider_session_id: str = ""

    @property
    def title(self) -> str:
        for turn in self.turns:
            if turn.role == "user" and turn.text.strip():
                return turn.text.strip().splitlines()[0][:120]
        return "New conversation"


@dataclass(slots=True)
class AdapterOutcome:
    ok: bool
    turns: list[Turn] = field(default_factory=list)
    provider_session_id: str = ""
    error_message: str = ""


class AgentAdapter:
    """One instance per supported agent CLI.

    An adapter only ever needs to be trusted for two things: which argv it
    builds (must never include a bypass/yolo flag for MODE_RUN or MODE_PLAN,
    enforced both here defensively and by tests/test_agent_adapters.py), and
    how it turns that CLI's own output shape back into normalized Turns.
    """

    name: str = ""
    supported_modes: frozenset[str] = frozenset()
    # Human-readable reason a mode isn't in supported_modes, e.g. because the
    # CLI has no confirmed non-interactive permission surface for it yet.
    unsupported_reason: str = ""

    def available(self) -> bool:
        return shutil.which(self.name) is not None

    def build_argv(self, request: AgentRequest) -> list[str]:
        raise NotImplementedError

    def parse_line(self, line: str, request: AgentRequest) -> Turn | None:
        """Called once per streamed stdout line. Most adapters only produce a
        turn once the process exits (finalize); override for adapters whose
        CLI emits real incremental JSON-lines events (e.g. codex --json)."""
        return None

    def finalize(self, stdout_text: str, stderr_text: str, returncode: int,
                 request: AgentRequest) -> AdapterOutcome:
        raise NotImplementedError

    def assert_safe_argv(self, argv: Sequence[str]) -> None:
        lowered = {str(value).lower() for value in argv}
        forbidden = lowered.intersection(flag.lower() for flag in FORBIDDEN_RUN_FLAGS)
        if forbidden:
            raise RuntimeError(
                f"{self.name} adapter built a forbidden bypass flag: {sorted(forbidden)}"
            )


_REGISTRY: dict[str, AgentAdapter] = {}


def register(adapter: AgentAdapter) -> AgentAdapter:
    _REGISTRY[adapter.name] = adapter
    return adapter


def all_adapters() -> dict[str, AgentAdapter]:
    return dict(_REGISTRY)


def get_adapter(name: str) -> AgentAdapter | None:
    return _REGISTRY.get(str(name or ""))


OnTurn = Callable[[Turn], "Awaitable[None] | None"]
