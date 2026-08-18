from __future__ import annotations

import sys
import unittest

from everything.commands import CommandRunner, CommandTimeout, safe_argv


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


if __name__ == "__main__":
    unittest.main()

