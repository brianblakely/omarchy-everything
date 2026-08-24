from __future__ import annotations

from ..base import AdapterOutcome, AgentAdapter, AgentRequest


class CrushAdapter(AgentAdapter):
    """Registered so an installed `crush` shows up in capabilities.agents,
    but not wired to run anything yet: `crush run --help` exposes no
    permission/sandbox/approval flag at all, so whether it prompts
    interactively (would hang here) or applies some default tool policy is
    unverified. Wiring this up for real needs that verified against a live
    instance first."""

    name = "crush"
    supported_modes = frozenset()
    unsupported_reason = (
        "crush's non-interactive permission behavior for `crush run` is unverified; not wired up yet"
    )
    supports_resume = False

    def build_argv(self, request: AgentRequest) -> list[str]:
        raise NotImplementedError("crush has no supported modes")

    def finalize(self, stdout_text: str, stderr_text: str, returncode: int,
                 request: AgentRequest) -> AdapterOutcome:
        return AdapterOutcome(ok=False, error_message=self.unsupported_reason)
