from __future__ import annotations

import unittest

from everything.agent.adapters import all_adapters
from everything.agent.adapters.claude import ClaudeAdapter
from everything.agent.adapters.codex import CodexAdapter
from everything.agent.adapters.crush import CrushAdapter
from everything.agent.adapters.gemini import GeminiAdapter
from everything.agent.adapters.opencode import OpenCodeAdapter
from everything.agent.base import FORBIDDEN_RUN_FLAGS, MODE_ASK, MODE_PLAN, MODE_RUN, MODES, AgentRequest


class NeverBypassTests(unittest.TestCase):
    """The single most safety-relevant property of this subsystem: RUN and
    PLAN argv for every registered adapter must never include a bypass/yolo
    flag. This is the one property most worth guarding with a test that
    iterates every adapter automatically, so a new adapter is covered without
    anyone remembering to add a case for it."""

    def test_no_registered_adapter_ever_emits_a_bypass_flag(self) -> None:
        for name, adapter in all_adapters().items():
            for mode in (MODE_PLAN, MODE_RUN):
                if mode not in adapter.supported_modes:
                    continue
                request = AgentRequest(
                    agent=name, mode=mode, prompt="do something",
                    allowed_dirs=("/tmp/allowed-a", "/tmp/allowed-b"),
                )
                argv = adapter.build_argv(request)
                lowered = {str(value).lower() for value in argv}
                forbidden = lowered.intersection(flag.lower() for flag in FORBIDDEN_RUN_FLAGS)
                self.assertFalse(
                    forbidden,
                    f"{name} {mode} argv contains forbidden flag(s) {forbidden}: {argv}",
                )
                # assert_safe_argv is the runtime guard the real runner calls;
                # confirm it agrees (would raise if it found the same thing).
                adapter.assert_safe_argv(argv)

    def test_unsupported_modes_are_excluded_rather_than_approximated(self) -> None:
        # Locks in the deliberate, documented scope decision: an adapter with
        # no confirmed non-interactive permission surface for a mode must not
        # silently claim to support it.
        self.assertEqual(CodexAdapter().supported_modes, frozenset({MODE_PLAN, MODE_RUN}))
        self.assertEqual(GeminiAdapter().supported_modes, frozenset({MODE_PLAN, MODE_RUN}))
        self.assertEqual(OpenCodeAdapter().supported_modes, frozenset())
        self.assertEqual(CrushAdapter().supported_modes, frozenset())
        self.assertTrue(OpenCodeAdapter().unsupported_reason)
        self.assertTrue(CrushAdapter().unsupported_reason)


class ClaudeAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = ClaudeAdapter()

    def test_prompt_is_the_first_argv_token(self) -> None:
        # Regression test for a confirmed real bug: --tools/--add-dir are
        # variadic and swallow a following bare positional prompt as more of
        # their own values ("claude -p --tools '' 'prompt'" fails because
        # "prompt" is treated as a tool name). Prompt must come first.
        for mode in MODES:
            request = AgentRequest(agent="claude", mode=mode, prompt="find the bug", allowed_dirs=("/tmp/x",))
            argv = self.adapter.build_argv(request)
            self.assertEqual(argv[0], "claude")
            self.assertEqual(argv[1], "find the bug")

    def test_ask_mode_disables_all_tools(self) -> None:
        request = AgentRequest(agent="claude", mode=MODE_ASK, prompt="what does this do", allowed_dirs=())
        argv = self.adapter.build_argv(request)
        self.assertIn("--tools", argv)
        self.assertEqual(argv[argv.index("--tools") + 1], "")

    def test_plan_mode_uses_read_only_permission_mode(self) -> None:
        request = AgentRequest(agent="claude", mode=MODE_PLAN, prompt="plan it", allowed_dirs=("/tmp/x",))
        argv = self.adapter.build_argv(request)
        self.assertIn("--permission-mode", argv)
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "plan")

    def test_run_mode_scopes_tools_and_dirs(self) -> None:
        request = AgentRequest(
            agent="claude", mode=MODE_RUN, prompt="fix it", allowed_dirs=("/tmp/a", "/tmp/b"),
        )
        argv = self.adapter.build_argv(request)
        self.assertIn("--add-dir", argv)
        add_dir_index = argv.index("--add-dir")
        self.assertEqual(argv[add_dir_index + 1 :], ["/tmp/a", "/tmp/b"])
        self.assertNotIn("Bash", argv[argv.index("--tools") + 1])

    def test_resume_session_id_is_forwarded(self) -> None:
        request = AgentRequest(
            agent="claude", mode=MODE_ASK, prompt="continue", resume_session_id="abc-123",
        )
        argv = self.adapter.build_argv(request)
        self.assertIn("--resume", argv)
        self.assertEqual(argv[argv.index("--resume") + 1], "abc-123")

    def test_finalize_parses_the_confirmed_success_shape(self) -> None:
        payload = (
            '{"is_error":false,"subtype":"success","session_id":"sid-1","result":"pong"}'
        )
        outcome = self.adapter.finalize(payload, "", 0, AgentRequest(agent="claude", mode=MODE_ASK, prompt="p"))
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.turns[0].text, "pong")
        self.assertEqual(outcome.provider_session_id, "sid-1")

    def test_finalize_reports_is_error(self) -> None:
        payload = '{"is_error":true,"session_id":"sid-2","result":"permission denied"}'
        outcome = self.adapter.finalize(payload, "", 0, AgentRequest(agent="claude", mode=MODE_RUN, prompt="p"))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.provider_session_id, "sid-2")

    def test_finalize_handles_malformed_json(self) -> None:
        outcome = self.adapter.finalize("not json", "", 1, AgentRequest(agent="claude", mode=MODE_ASK, prompt="p"))
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.error_message)

    def test_finalize_handles_empty_output(self) -> None:
        outcome = self.adapter.finalize("", "boom", 1, AgentRequest(agent="claude", mode=MODE_ASK, prompt="p"))
        self.assertFalse(outcome.ok)
        self.assertIn("boom", outcome.error_message)


class CodexAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CodexAdapter()

    def test_plan_mode_uses_read_only_sandbox(self) -> None:
        request = AgentRequest(agent="codex", mode=MODE_PLAN, prompt="investigate", allowed_dirs=("/tmp/x",))
        argv = self.adapter.build_argv(request)
        self.assertIn("--sandbox", argv)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "read-only")

    def test_run_mode_uses_workspace_write_sandbox_and_extra_dirs(self) -> None:
        request = AgentRequest(agent="codex", mode=MODE_RUN, prompt="fix", allowed_dirs=("/tmp/a", "/tmp/b"))
        argv = self.adapter.build_argv(request)
        self.assertEqual(argv[argv.index("--sandbox") + 1], "workspace-write")
        self.assertEqual(argv.count("--add-dir"), 1)  # only the *extra* dirs; the first is the cwd

    def test_parse_line_extracts_agent_message_text(self) -> None:
        request = AgentRequest(agent="codex", mode=MODE_PLAN, prompt="p")
        line = '{"type":"item.completed","item":{"type":"agent_message","text":"here is the plan"}}'
        turn = self.adapter.parse_line(line, request)
        self.assertIsNotNone(turn)
        self.assertEqual(turn.text, "here is the plan")

    def test_parse_line_ignores_non_message_events(self) -> None:
        request = AgentRequest(agent="codex", mode=MODE_PLAN, prompt="p")
        self.assertIsNone(self.adapter.parse_line('{"type":"turn.started"}', request))
        self.assertIsNone(self.adapter.parse_line("not json at all", request))

    def test_finalize_detects_turn_failed(self) -> None:
        stdout = (
            '{"type":"thread.started","thread_id":"t1"}\n'
            '{"type":"turn.failed","error":{"message":"boom"}}\n'
        )
        outcome = self.adapter.finalize(stdout, "", 0, AgentRequest(agent="codex", mode=MODE_PLAN, prompt="p"))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.provider_session_id, "t1")
        self.assertIn("boom", outcome.error_message)

    def test_finalize_ok_when_a_message_was_seen(self) -> None:
        stdout = (
            '{"type":"thread.started","thread_id":"t2"}\n'
            '{"type":"item.completed","item":{"type":"agent_message","text":"done"}}\n'
        )
        outcome = self.adapter.finalize(stdout, "", 0, AgentRequest(agent="codex", mode=MODE_PLAN, prompt="p"))
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.provider_session_id, "t2")
        self.assertEqual(outcome.turns, [])  # already streamed live via parse_line


class GeminiAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = GeminiAdapter()

    def test_run_mode_uses_auto_edit_not_yolo(self) -> None:
        request = AgentRequest(agent="gemini", mode=MODE_RUN, prompt="fix", allowed_dirs=("/tmp/a",))
        argv = self.adapter.build_argv(request)
        self.assertEqual(argv[argv.index("--approval-mode") + 1], "auto_edit")

    def test_skip_trust_is_always_present(self) -> None:
        # Confirmed live: without --skip-trust, gemini silently overrides an
        # explicit --approval-mode back to "default" for an untrusted folder.
        for mode in (MODE_PLAN, MODE_RUN):
            request = AgentRequest(agent="gemini", mode=mode, prompt="p", allowed_dirs=("/tmp/a",))
            self.assertIn("--skip-trust", self.adapter.build_argv(request))

    def test_finalize_parses_confirmed_error_shape(self) -> None:
        payload = '{"session_id":"g1","error":{"type":"Error","message":"no auth","code":41}}'
        outcome = self.adapter.finalize(payload, "", 0, AgentRequest(agent="gemini", mode=MODE_PLAN, prompt="p"))
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.provider_session_id, "g1")
        self.assertIn("no auth", outcome.error_message)

    def test_finalize_falls_back_to_raw_json_for_unrecognized_success_shape(self) -> None:
        payload = '{"session_id":"g2","somethingElse":"hi"}'
        outcome = self.adapter.finalize(payload, "", 0, AgentRequest(agent="gemini", mode=MODE_PLAN, prompt="p"))
        self.assertTrue(outcome.ok)
        self.assertIn("somethingElse", outcome.turns[0].text)

    def test_finalize_prefers_known_text_fields(self) -> None:
        payload = '{"session_id":"g3","response":"the answer"}'
        outcome = self.adapter.finalize(payload, "", 0, AgentRequest(agent="gemini", mode=MODE_PLAN, prompt="p"))
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.turns[0].text, "the answer")


class UnsupportedAdapterTests(unittest.TestCase):
    def test_opencode_and_crush_fail_clearly_rather_than_silently(self) -> None:
        for adapter in (OpenCodeAdapter(), CrushAdapter()):
            outcome = adapter.finalize("", "", 0, AgentRequest(agent=adapter.name, mode=MODE_RUN, prompt="p"))
            self.assertFalse(outcome.ok)
            self.assertTrue(outcome.error_message)


if __name__ == "__main__":
    unittest.main()
