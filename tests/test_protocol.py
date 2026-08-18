from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class ProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.process = subprocess.Popen(
            [sys.executable, str(ROOT / "helper/everything_helper.py"), "--json-lines", "--test-mode"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
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

    def request(self, value: dict) -> dict:
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(json.dumps(value) + "\n")
        self.process.stdin.flush()
        return json.loads(self.process.stdout.readline())

    def test_ready_and_correlated_full_snapshot(self) -> None:
        self.assertEqual(self.ready["type"], "ready")
        self.assertEqual(self.ready["version"], 1)
        response = self.request(
            {"version": 1, "id": "scan-test", "type": "scan", "options": {"ghostty": False}}
        )
        self.assertEqual(response["type"], "snapshot")
        self.assertEqual(response["requestId"], "scan-test")
        self.assertTrue(response["full"])

    def test_malformed_and_unknown_requests_are_nonfatal(self) -> None:
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write("not-json\n")
        self.process.stdin.flush()
        malformed = json.loads(self.process.stdout.readline())
        self.assertEqual(malformed["type"], "error")
        self.assertTrue(malformed["nonfatal"])
        unknown = self.request({"version": 1, "id": "bad", "type": "explode"})
        self.assertEqual(unknown["requestId"], "bad")
        self.assertEqual(unknown["type"], "error")

    def test_unknown_activation_is_stale(self) -> None:
        response = self.request(
            {"version": 1, "id": "activation", "type": "activate", "itemId": "none", "token": "x"}
        )
        self.assertEqual(response["type"], "activation")
        self.assertFalse(response["ok"])
        self.assertTrue(response["stale"])


if __name__ == "__main__":
    unittest.main()
