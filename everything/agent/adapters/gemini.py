from __future__ import annotations

import json

from ..base import MODE_PLAN, MODE_RUN, AdapterOutcome, AgentAdapter, AgentRequest, Turn

# gemini's --allowed-tools flag is documented deprecated in favor of a policy
# engine we haven't verified, and there is no confirmed tool-free mode, so
# MODE_ASK is excluded the same way as codex rather than guessed at.
_UNSUPPORTED_ASK = "gemini has no confirmed tool-free answer-only mode; only plan and run are supported"

# Fields tried in order when locating the answer text in gemini's `-o json`
# result. Confirmed live on this machine: the error shape is
# {"session_id":..., "error":{"type","message","code"}}; the success shape's
# exact field name was not observed (no credentials configured in this
# sandbox), so success falls back to a labeled raw dump rather than silently
# dropping content if none of these match.
_TEXT_FIELDS = ("response", "result", "text", "answer", "content")


class GeminiAdapter(AgentAdapter):
    name = "gemini"
    supported_modes = frozenset({MODE_PLAN, MODE_RUN})
    unsupported_reason = _UNSUPPORTED_ASK
    supports_resume = False  # --resume takes "latest" or an index, not a session id we can store

    def build_argv(self, request: AgentRequest) -> list[str]:
        approval = "plan" if request.mode == MODE_PLAN else "auto_edit"
        argv = [
            "gemini", "-p", request.prompt,
            "-o", "json",
            "--approval-mode", approval,
            # Without this, gemini silently overrides an explicit
            # --approval-mode back to "default" for an untrusted folder,
            # observed live on this machine — defeating the requested mode.
            "--skip-trust",
        ]
        if request.allowed_dirs:
            argv += ["--include-directories", ",".join(request.allowed_dirs)]
        return argv

    def finalize(self, stdout_text: str, stderr_text: str, returncode: int,
                 request: AgentRequest) -> AdapterOutcome:
        text = stdout_text.strip()
        if not text:
            return AdapterOutcome(
                ok=False,
                error_message=stderr_text.strip() or f"gemini exited {returncode} with no output",
            )
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return AdapterOutcome(ok=False, error_message="gemini returned output that was not valid JSON")
        if not isinstance(payload, dict):
            return AdapterOutcome(ok=False, error_message="gemini returned a non-object JSON result")

        session_id = str(payload.get("session_id") or "")
        error = payload.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "gemini reported an error")
            return AdapterOutcome(ok=False, provider_session_id=session_id, error_message=message)

        for field in _TEXT_FIELDS:
            value = payload.get(field)
            if isinstance(value, str) and value.strip():
                return AdapterOutcome(ok=True, turns=[Turn("assistant", value)], provider_session_id=session_id)
        # Unrecognized success shape: surface the raw JSON rather than lose it.
        return AdapterOutcome(
            ok=True,
            turns=[Turn("assistant", json.dumps(payload, indent=2))],
            provider_session_id=session_id,
        )
