from __future__ import annotations

from ..commands import CommandError, CommandRunner

# The name omarchy-default-agent prints does not always match the CLI binary
# name an adapter is registered under (e.g. "claude-code" vs "claude"). Keep
# that mapping here, next to the one place that calls the command, rather
# than inside every adapter.
_CLI_NAME_BY_OMARCHY_NAME = {
    "claude": "claude",
    "codex": "codex",
    "gemini": "gemini",
    "opencode": "opencode",
    "crush": "crush",
    "pi": "pi",
    "omp": "omp",
    "grok": "grok",
    "copilot": "copilot",
}


async def resolve_default_agent(runner: CommandRunner) -> str:
    """Return the adapter name for the user's configured default agent.

    Server-side only: QML never calls native tools directly (see
    docs/architecture.md). Empty string means Omarchy has no default agent
    configured yet, matching omarchy-default-agent's own convention of
    printing nothing rather than guessing.
    """
    try:
        result = await runner.run(["omarchy-default-agent"], timeout=2.0)
    except CommandError:
        return ""
    name = result.stdout.strip().splitlines()[0].strip() if result.stdout.strip() else ""
    return _CLI_NAME_BY_OMARCHY_NAME.get(name, name)
