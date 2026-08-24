from __future__ import annotations

import os

from ..commands import CommandRunner
from .base import (
    DEFAULT_IDLE_TIMEOUT_SECONDS,
    DEFAULT_TIMEOUT_SECONDS,
    MODE_PLAN,
    MODE_RUN,
    AdapterOutcome,
    AgentAdapter,
    AgentRequest,
    OnTurn,
)


async def run_agent(
    runner: CommandRunner,
    adapter: AgentAdapter,
    request: AgentRequest,
    on_turn: OnTurn,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    idle_timeout: float = DEFAULT_IDLE_TIMEOUT_SECONDS,
) -> AdapterOutcome:
    """Drive one agent CLI invocation through to a normalized outcome.

    Every safety-relevant decision lives here, not scattered across callers:
    mode support and resume support are checked before any process starts,
    RUN/PLAN argv is asserted free of bypass/yolo flags right before exec,
    and the working directory is the first configured allowed dir (never an
    arbitrary caller-supplied path) or None.
    """
    if request.mode not in adapter.supported_modes:
        reason = adapter.unsupported_reason or f"{adapter.name} does not support {request.mode} mode yet"
        return AdapterOutcome(ok=False, error_message=reason)
    if request.resume_session_id and not getattr(adapter, "supports_resume", False):
        return AdapterOutcome(
            ok=False,
            error_message=f"{adapter.name} cannot resume a previous conversation yet",
        )
    if not adapter.available():
        return AdapterOutcome(ok=False, error_message=f"{adapter.name} is not installed")

    argv = adapter.build_argv(request)
    if request.mode in (MODE_RUN, MODE_PLAN):
        adapter.assert_safe_argv(argv)

    cwd = request.allowed_dirs[0] if request.allowed_dirs else None
    if cwd and not os.path.isdir(cwd):
        cwd = None

    async def handle_line(line: str) -> None:
        turn = adapter.parse_line(line, request)
        if turn is not None:
            result = on_turn(turn)
            if result is not None:
                await result

    try:
        result = await runner.run_streaming(
            argv,
            on_line=handle_line,
            timeout=timeout,
            idle_timeout=idle_timeout,
            cwd=cwd,
        )
    except Exception as error:  # CommandTimeout / OSError / adapter.available() surprises
        return AdapterOutcome(ok=False, error_message=str(error))

    return adapter.finalize(result.stdout, result.stderr, result.returncode, request)
