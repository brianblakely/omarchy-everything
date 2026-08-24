from __future__ import annotations

import json

from ..base import MODE_ASK, MODE_PLAN, MODE_RUN, AdapterOutcome, AgentAdapter, AgentRequest, Turn

# Tools deliberately excluded from MODE_RUN: no Bash (would need per-command
# approval this non-interactive path can't give without a bypass flag), no
# WebFetch/WebSearch (this subsystem's whole premise is a locally-scoped,
# opt-in addition, not a new arbitrary network egress path).
_RUN_TOOLS = "Read,Write,Edit,Glob,Grep"


class ClaudeAdapter(AgentAdapter):
    name = "claude"
    supported_modes = frozenset({MODE_ASK, MODE_PLAN, MODE_RUN})
    supports_resume = True

    def build_argv(self, request: AgentRequest) -> list[str]:
        # The prompt goes first. --tools/--add-dir are documented as taking
        # "<tools...>"/"<directories...>" (variadic) and will otherwise
        # swallow a following bare positional prompt as more of their own
        # values (confirmed: `claude -p --tools "" "prompt"` fails with
        # "prompt must be provided" because "prompt" got treated as a tool
        # name). Putting the prompt first side-steps that entirely.
        argv = ["claude", request.prompt, "-p", "--output-format", "json"]
        if request.resume_session_id:
            argv += ["--resume", request.resume_session_id]

        if request.mode == MODE_ASK:
            argv += ["--tools", ""]
        elif request.mode == MODE_PLAN:
            argv += ["--permission-mode", "plan"]
        elif request.mode == MODE_RUN:
            argv += ["--permission-mode", "acceptEdits", "--tools", _RUN_TOOLS]

        if request.allowed_dirs and request.mode in (MODE_PLAN, MODE_RUN):
            # Variadic and last: nothing follows it in this argv.
            argv += ["--add-dir", *request.allowed_dirs]
        return argv

    def finalize(self, stdout_text: str, stderr_text: str, returncode: int,
                 request: AgentRequest) -> AdapterOutcome:
        text = stdout_text.strip()
        if not text:
            return AdapterOutcome(
                ok=False,
                error_message=stderr_text.strip() or f"claude exited {returncode} with no output",
            )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return AdapterOutcome(ok=False, error_message="claude returned output that was not valid JSON")
        if not isinstance(payload, dict):
            return AdapterOutcome(ok=False, error_message="claude returned a non-object JSON result")

        session_id = str(payload.get("session_id") or "")
        if payload.get("is_error") is True or payload.get("subtype") not in (None, "success"):
            message = str(payload.get("result") or payload.get("subtype") or "claude reported an error")
            return AdapterOutcome(ok=False, turns=[], provider_session_id=session_id, error_message=message)

        result_text = payload.get("result")
        answer = str(result_text) if isinstance(result_text, str) else json.dumps(payload)
        return AdapterOutcome(ok=True, turns=[Turn("assistant", answer)], provider_session_id=session_id)
