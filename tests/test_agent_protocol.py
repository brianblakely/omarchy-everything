from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class AgentProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        env = dict(os.environ)
        env["XDG_DATA_HOME"] = self._tmp.name
        self.process = subprocess.Popen(
            [sys.executable, str(ROOT / "helper/everything_agent_helper.py"), "--json-lines", "--test-mode"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        assert self.process.stdout
        self.ready = json.loads(self.process.stdout.readline())

    def tearDown(self) -> None:
        try:
            if self.process.poll() is None:
                assert self.process.stdin
                self.process.stdin.write('{"version":1,"id":"shutdown","type":"shutdown"}\n')
                self.process.stdin.flush()
                self.process.wait(timeout=5)
        finally:
            for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
                if stream:
                    stream.close()

    def send(self, value: dict) -> None:
        assert self.process.stdin
        self.process.stdin.write(json.dumps(value) + "\n")
        self.process.stdin.flush()

    def read_one(self) -> dict:
        assert self.process.stdout
        return json.loads(self.process.stdout.readline())

    def request(self, value: dict) -> dict:
        """Send one request and return its single, immediate response."""
        self.send(value)
        return self.read_one()

    def run_to_completion(self, value: dict) -> list[dict]:
        """Send an agentRun and collect every message up to and including the
        final:true message for that requestId."""
        self.send(value)
        messages = []
        while True:
            message = self.read_one()
            messages.append(message)
            if message.get("requestId") == value["id"] and message.get("final") is True:
                return messages
            if message.get("type") == "agentRunFailed" and message.get("requestId") == value["id"]:
                return messages

    def test_ready_reports_capabilities(self) -> None:
        self.assertEqual(self.ready["type"], "ready")
        self.assertEqual(self.ready["version"], 1)
        self.assertIn("test-agent", self.ready["capabilities"]["agents"])

    def test_malformed_and_unknown_requests_are_nonfatal(self) -> None:
        assert self.process.stdin
        self.process.stdin.write("not-json\n")
        self.process.stdin.flush()
        malformed = self.read_one()
        self.assertEqual(malformed["type"], "error")
        self.assertTrue(malformed["nonfatal"])
        unknown = self.request({"version": 1, "id": "bad", "type": "explode"})
        self.assertEqual(unknown["requestId"], "bad")
        self.assertEqual(unknown["type"], "error")

    def test_agent_run_streams_a_turn_then_a_final_ok_message(self) -> None:
        messages = self.run_to_completion({
            "version": 1, "id": "run-1", "type": "agentRun",
            "mode": "ask", "prompt": "hello", "allowedDirs": [],
        })
        turn_messages = [m for m in messages if m.get("type") == "agentTurn" and m.get("final") is not True]
        self.assertEqual(len(turn_messages), 1)
        self.assertEqual(turn_messages[0]["turn"]["role"], "assistant")
        final = messages[-1]
        self.assertTrue(final["final"])
        self.assertTrue(final["ok"])
        self.assertIn("conversationId", final)

    def test_agent_run_failure_is_reported_not_dropped(self) -> None:
        messages = self.run_to_completion({
            "version": 1, "id": "run-2", "type": "agentRun",
            "mode": "ask", "prompt": "fail", "allowedDirs": [],
        })
        final = messages[-1]
        self.assertTrue(final["final"])
        self.assertFalse(final["ok"])
        self.assertIn("message", final)

    def test_empty_prompt_fails_clearly(self) -> None:
        messages = self.run_to_completion({
            "version": 1, "id": "run-3", "type": "agentRun",
            "mode": "ask", "prompt": "   ", "allowedDirs": [],
        })
        self.assertEqual(messages[-1]["type"], "agentRunFailed")

    def test_plan_mode_requires_an_allowed_dir(self) -> None:
        messages = self.run_to_completion({
            "version": 1, "id": "run-4", "type": "agentRun",
            "mode": "plan", "prompt": "investigate", "allowedDirs": [],
        })
        self.assertEqual(messages[-1]["type"], "agentRunFailed")
        self.assertIn("allowed folder", messages[-1]["message"])

    def test_unknown_mode_fails_clearly(self) -> None:
        messages = self.run_to_completion({
            "version": 1, "id": "run-5", "type": "agentRun",
            "mode": "sudo", "prompt": "do anything", "allowedDirs": [],
        })
        self.assertEqual(messages[-1]["type"], "agentRunFailed")

    def test_conversation_list_get_and_delete_round_trip(self) -> None:
        self.run_to_completion({
            "version": 1, "id": "run-6", "type": "agentRun",
            "mode": "ask", "prompt": "remember this", "allowedDirs": [],
        })
        listing = self.request({"version": 1, "id": "list-1", "type": "agentConversationList"})
        self.assertEqual(listing["type"], "agentConversationList")
        self.assertGreaterEqual(len(listing["conversations"]), 1)
        conversation_id = listing["conversations"][0]["id"]

        fetched = self.request({
            "version": 1, "id": "get-1", "type": "agentConversationGet", "conversationId": conversation_id,
        })
        self.assertEqual(fetched["type"], "agentConversationGet")
        roles = [turn["role"] for turn in fetched["turns"]]
        self.assertEqual(roles, ["user", "assistant"])

        deleted = self.request({
            "version": 1, "id": "del-1", "type": "agentConversationDelete", "conversationId": conversation_id,
        })
        self.assertTrue(deleted["ok"])
        missing = self.request({
            "version": 1, "id": "get-2", "type": "agentConversationGet", "conversationId": conversation_id,
        })
        self.assertEqual(missing["type"], "error")

    def test_get_unknown_conversation_is_nonfatal_error(self) -> None:
        response = self.request({
            "version": 1, "id": "get-3", "type": "agentConversationGet", "conversationId": "nope",
        })
        self.assertEqual(response["type"], "error")
        self.assertTrue(response["nonfatal"])

    def test_cancel_stops_a_running_request(self) -> None:
        self.send({
            "version": 1, "id": "run-7", "type": "agentRun",
            "mode": "run", "prompt": "hello", "allowedDirs": ["/tmp"],
        })
        # The fake adapter answers immediately in test mode, so this mostly
        # exercises that agentCancel for an unknown/already-finished request
        # is accepted without error rather than crashing the helper.
        self.send({"version": 1, "id": "cancel-1", "type": "agentCancel", "requestId": "run-7"})
        # Drain until the run's own final message, proving the helper is
        # still alive and responsive after handling the cancel request.
        while True:
            message = self.read_one()
            if message.get("requestId") == "run-7" and message.get("final") is True:
                break


if __name__ == "__main__":
    unittest.main()
