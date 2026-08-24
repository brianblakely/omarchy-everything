from __future__ import annotations

import asyncio
import os
import sys
import unittest

from everything.commands import CommandRunner, CommandTimeout, safe_argv


# safe_argv() rejects any argv value containing a newline, including -c
# script bodies, so these stay single lines.
_STREAM_SCRIPT = "import sys; [(print(v), sys.stdout.flush()) for v in sys.argv[1:]]"
_TALKATIVE_SCRIPT = (
    "import sys, time; [(print(i), sys.stdout.flush(), time.sleep(0.01)) for i in range(1000)]"
)


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


class StreamingTests(unittest.IsolatedAsyncioTestCase):
    async def test_lines_arrive_in_order(self) -> None:
        lines: list[str] = []

        async def on_line(line: str) -> None:
            lines.append(line)

        result = await CommandRunner().run_streaming(
            [sys.executable, "-c", _STREAM_SCRIPT, "one", "two", "three"],
            on_line=on_line,
            timeout=10,
            idle_timeout=10,
        )
        self.assertEqual(lines, ["one", "two", "three"])
        self.assertEqual(result.returncode, 0)

    async def test_on_line_may_be_synchronous(self) -> None:
        lines: list[str] = []
        result = await CommandRunner().run_streaming(
            [sys.executable, "-c", _STREAM_SCRIPT, "a", "b"],
            on_line=lines.append,
            timeout=10,
            idle_timeout=10,
        )
        self.assertEqual(lines, ["a", "b"])
        self.assertEqual(result.returncode, 0)

    async def test_idle_timeout_kills_a_silent_child(self) -> None:
        with self.assertRaises(CommandTimeout):
            await CommandRunner().run_streaming(
                [sys.executable, "-c", "import time; time.sleep(10)"],
                on_line=lambda _line: None,
                timeout=10,
                idle_timeout=0.05,
            )

    async def test_overall_timeout_kills_a_talkative_child(self) -> None:
        with self.assertRaises(CommandTimeout):
            await CommandRunner().run_streaming(
                [sys.executable, "-c", _TALKATIVE_SCRIPT],
                on_line=lambda _line: None,
                timeout=0.1,
                idle_timeout=10,
            )

    async def test_cancellation_kills_the_subprocess(self) -> None:
        started = False

        async def on_line(_line: str) -> None:
            nonlocal started
            started = True

        async def run() -> None:
            await CommandRunner().run_streaming(
                [sys.executable, "-c", "import sys, time; print('go'); sys.stdout.flush(); time.sleep(10)"],
                on_line=on_line,
                timeout=None,
                idle_timeout=None,
            )

        task = asyncio.ensure_future(run())
        while not started:
            await asyncio.sleep(0.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_argv_injection_is_still_rejected(self) -> None:
        with self.assertRaises(TypeError):
            await CommandRunner().run_streaming(
                "echo hi",  # type: ignore[arg-type]
                on_line=lambda _line: None,
            )

    async def test_cwd_is_honored(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            lines: list[str] = []
            await CommandRunner().run_streaming(
                [sys.executable, "-c", "import os; print(os.getcwd())"],
                on_line=lines.append,
                timeout=10,
                idle_timeout=10,
                cwd=tmp_dir,
            )
            self.assertEqual(lines[0], os.path.realpath(tmp_dir))


if __name__ == "__main__":
    unittest.main()

