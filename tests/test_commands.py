from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

from everything.commands import CommandRunner, CommandTimeout, safe_argv, unix_json_request


class ArgvTests(unittest.IsolatedAsyncioTestCase):
    def test_shell_strings_are_rejected(self) -> None:
        with self.assertRaises(TypeError):
            safe_argv("hyprctl -j clients")  # type: ignore[arg-type]

    async def test_metacharacters_are_literal_argv_data(self) -> None:
        marker = "$(touch /tmp/everything-must-not-exist);`false`"
        result = await CommandRunner().run([sys.executable, "-c", "import sys; print(sys.argv[1])", marker])
        self.assertEqual(result.stdout.strip(), marker)

    async def test_timeout_kills_the_child(self) -> None:
        with self.assertRaises(CommandTimeout):
            await CommandRunner(default_timeout=0.03).run(
                [sys.executable, "-c", "import time; time.sleep(10)"]
            )

    def test_newlines_and_nuls_are_rejected(self) -> None:
        for value in ("bad\narg", "bad\rarg", "bad\x00arg"):
            with self.assertRaises(ValueError):
                safe_argv(["tool", value])


class UnixJsonRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_response_larger_than_default_stream_limit_is_read(self) -> None:
        # asyncio's default StreamReader limit is 64 KiB; a Herdr snapshot
        # with a few dozen panes is larger than that.
        payload = {"result": {"padding": "x" * (200 * 1024)}}

        async def respond(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            await reader.readline()
            writer.write(json.dumps(payload).encode() + b"\n")
            await writer.drain()
            writer.close()

        with tempfile.TemporaryDirectory() as directory:
            socket_path = str(Path(directory, "server.sock"))
            server = await asyncio.start_unix_server(respond, socket_path)
            async with server:
                response = await unix_json_request(socket_path, {"id": "test"})
        self.assertEqual(response, payload)


if __name__ == "__main__":
    unittest.main()

