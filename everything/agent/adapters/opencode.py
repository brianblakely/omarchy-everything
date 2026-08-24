from __future__ import annotations

from ..base import AdapterOutcome, AgentAdapter, AgentRequest


class OpenCodeAdapter(AgentAdapter):
    """Registered so an installed `opencode` shows up in capabilities.agents,
    but not wired to run anything yet: `opencode run --help` exposes no
    permission/sandbox/approval flag at all except `--auto` ("auto-approve
    permissions that are not explicitly denied (dangerous!)"), which this
    subsystem's rule against bypass/yolo flags rules out, and without it the
    non-interactive default permission behavior is unverified. Wiring this up
    for real needs that verified against a live instance first."""

    name = "opencode"
    supported_modes = frozenset()
    unsupported_reason = (
        "opencode has no confirmed non-interactive permission mode that isn't "
        "--auto (dangerous!); not wired up yet"
    )
    supports_resume = False

    def build_argv(self, request: AgentRequest) -> list[str]:
        raise NotImplementedError("opencode has no supported modes")

    def finalize(self, stdout_text: str, stderr_text: str, returncode: int,
                 request: AgentRequest) -> AdapterOutcome:
        return AdapterOutcome(ok=False, error_message=self.unsupported_reason)
