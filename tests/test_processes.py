from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from everything.processes import ProcTable, ProcessInfo


class ProcessEnvironmentTests(unittest.TestCase):
    def test_reads_only_requested_values_from_a_same_user_process(self) -> None:
        with tempfile.TemporaryDirectory(prefix="everything-proc-") as root:
            pid = 42
            process_dir = Path(root, str(pid))
            process_dir.mkdir()
            process_dir.joinpath("environ").write_bytes(
                b"PRIVATE=value\0HERDR_SOCKET_PATH=/run/user/1000/herdr.sock\0"
                b"HERDR_PANE_ID=pane-7\0"
            )
            table = ProcTable(
                {pid: ProcessInfo(pid, 1, "birth", "nvim", ("nvim",), "/work")},
                uid=os.getuid(),
            )

            values = table.environment(
                pid,
                ("HERDR_SOCKET_PATH", "HERDR_PANE_ID"),
                proc_root=root,
            )

            self.assertEqual(
                values,
                {
                    "HERDR_SOCKET_PATH": "/run/user/1000/herdr.sock",
                    "HERDR_PANE_ID": "pane-7",
                },
            )
            self.assertNotIn("PRIVATE", values)

    def test_oversized_environment_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="everything-proc-") as root:
            pid = 43
            process_dir = Path(root, str(pid))
            process_dir.mkdir()
            process_dir.joinpath("environ").write_bytes(b"HERDR_PANE_ID=" + b"x" * 64)
            table = ProcTable(
                {pid: ProcessInfo(pid, 1, "birth", "nvim", ("nvim",), "/work")},
                uid=os.getuid(),
            )

            self.assertEqual(
                table.environment(pid, ("HERDR_PANE_ID",), proc_root=root, max_bytes=16),
                {},
            )


if __name__ == "__main__":
    unittest.main()
