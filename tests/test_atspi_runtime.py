from __future__ import annotations

import unittest

from everything.atspi_runtime import AtspiRuntimeLease


class FakeStatus:
    def __init__(self, enabled: bool, reader: bool) -> None:
        self.values = {"IsEnabled": enabled, "ScreenReaderEnabled": reader}
        self.writes: list[tuple[str, bool]] = []

    def get(self, name: str) -> bool:
        return self.values[name]

    def set(self, name: str, value: bool) -> None:
        self.values[name] = value
        self.writes.append((name, value))


class AtspiLeaseTests(unittest.TestCase):
    def test_disabled_state_is_restored(self) -> None:
        backend = FakeStatus(False, False)
        lease = AtspiRuntimeLease(backend)
        lease.acquire()
        self.assertTrue(backend.values["IsEnabled"])
        lease.restore()
        self.assertFalse(backend.values["IsEnabled"])
        self.assertEqual(backend.writes, [("IsEnabled", True), ("IsEnabled", False)])

    def test_existing_enabled_state_is_untouched(self) -> None:
        backend = FakeStatus(True, False)
        lease = AtspiRuntimeLease(backend)
        lease.acquire()
        lease.restore()
        self.assertEqual(backend.writes, [])

    def test_screen_reader_mode_is_never_written(self) -> None:
        backend = FakeStatus(False, True)
        lease = AtspiRuntimeLease(backend)
        lease.acquire()
        lease.restore()
        self.assertNotIn("ScreenReaderEnabled", [name for name, _value in backend.writes])
        self.assertTrue(backend.values["ScreenReaderEnabled"])


if __name__ == "__main__":
    unittest.main()

