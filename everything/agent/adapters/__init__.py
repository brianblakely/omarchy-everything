from __future__ import annotations

from ..base import all_adapters, get_adapter, register  # noqa: F401
from . import claude, codex, crush, gemini, opencode  # noqa: F401

register(claude.ClaudeAdapter())
register(codex.CodexAdapter())
register(gemini.GeminiAdapter())
register(opencode.OpenCodeAdapter())
register(crush.CrushAdapter())
