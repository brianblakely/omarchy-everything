from __future__ import annotations

import json

from ..base import MODE_PLAN, MODE_RUN, AdapterOutcome, AgentAdapter, AgentRequest, Turn

# codex exec has no confirmed flag for a tool-free "just answer" mode (its
# model always operates through the sandboxed shell for both reading and
# writing, unlike Claude Code's separate Read/Edit/Bash tool list) so MODE_ASK
# is deliberately not offered here rather than approximated incorrectly.
_UNSUPPORTED_ASK = "codex has no confirmed tool-free answer-only mode; only plan and run are supported"


class CodexAdapter(AgentAdapter):
    name = "codex"
    supported_modes = frozenset({MODE_PLAN, MODE_RUN})
    unsupported_reason = _UNSUPPORTED_ASK
    supports_resume = False  # codex exec's resume subcommand shape is not yet verified against a live session

    def build_argv(self, request: AgentRequest) -> list[str]:
        sandbox = "read-only" if request.mode == MODE_PLAN else "workspace-write"
        argv = [
            "codex", "exec", request.prompt,
            "--sandbox", sandbox,
            # Allowed dirs are user-configured trust, not an ambient git repo;
            # codex otherwise refuses to run outside one.
            "--skip-git-repo-check",
            "--json",
        ]
        for directory in request.allowed_dirs[1:]:
            argv += ["--add-dir", directory]
        return argv

    def parse_line(self, line: str, request: AgentRequest) -> Turn | None:
        event = _parse_event(line)
        if not event or event.get("type") != "item.completed":
            return None
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "agent_message":
            return None
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            return Turn("assistant", text)
        return None

    def finalize(self, stdout_text: str, stderr_text: str, returncode: int,
                 request: AgentRequest) -> AdapterOutcome:
        # Turns were already emitted live via parse_line/on_turn; this pass
        # only determines the outcome and picks up the session id, so nothing
        # here is re-appended to the transcript.
        session_id = ""
        failure: str | None = None
        saw_message = False
        for line in stdout_text.splitlines():
            event = _parse_event(line)
            if not event:
                continue
            event_type = event.get("type")
            if event_type == "thread.started":
                session_id = str(event.get("thread_id") or "")
            elif event_type == "item.completed":
                item = event.get("item")
                if isinstance(item, dict) and item.get("type") == "agent_message":
                    saw_message = True
            elif event_type in ("turn.failed", "error"):
                error = event.get("error")
                message = error.get("message") if isinstance(error, dict) else event.get("message")
                failure = str(message or "codex reported an error")

        if failure:
            return AdapterOutcome(ok=False, provider_session_id=session_id, error_message=failure)
        if returncode != 0:
            return AdapterOutcome(
                ok=False,
                provider_session_id=session_id,
                error_message=stderr_text.strip() or f"codex exited {returncode}",
            )
        if not saw_message:
            return AdapterOutcome(
                ok=False,
                provider_session_id=session_id,
                error_message="codex finished without producing a response",
            )
        return AdapterOutcome(ok=True, provider_session_id=session_id)


def _parse_event(line: str) -> dict | None:
    text = line.strip()
    if not text:
        return None
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None
