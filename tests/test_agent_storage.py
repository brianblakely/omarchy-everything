from __future__ import annotations

import json
import stat
import tempfile
import time
import unittest
from pathlib import Path

from everything.agent.base import Turn
from everything.agent.storage import MAX_TURN_TEXT_BYTES, ConversationStore, _TRUNCATION_MARKER


class ConversationStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = ConversationStore(root=Path(self._tmp.name) / "agent", retention_count=3)

    def test_directory_and_file_permissions_are_owner_only(self) -> None:
        self.assertEqual(stat.S_IMODE(self.store.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.store.conversations_dir.stat().st_mode), 0o700)
        conversation = self.store.create("claude", "ask", ())
        path = self.store._conversation_path(conversation.id)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_round_trip_create_append_get(self) -> None:
        conversation = self.store.create("claude", "ask", ("/tmp/a",))
        self.store.append_turn(conversation.id, Turn("user", "hello"))
        self.store.append_turn(conversation.id, Turn("assistant", "hi there"))
        loaded = self.store.get(conversation.id)
        self.assertIsNotNone(loaded)
        self.assertEqual([turn.role for turn in loaded.turns], ["user", "assistant"])
        self.assertEqual(loaded.turns[1].text, "hi there")
        self.assertEqual(loaded.allowed_dirs, ("/tmp/a",))

    def test_get_unknown_conversation_returns_none(self) -> None:
        self.assertIsNone(self.store.get("does-not-exist"))

    def test_title_derives_from_first_user_turn(self) -> None:
        conversation = self.store.create("claude", "ask", ())
        self.store.append_turn(conversation.id, Turn("user", "What does this repo do?\nMore detail here."))
        summaries = self.store.list_conversations()
        self.assertEqual(summaries[0].title, "What does this repo do?")

    def test_list_is_recent_first(self) -> None:
        first = self.store.create("claude", "ask", ())
        time.sleep(0.01)
        second = self.store.create("claude", "ask", ())
        summaries = self.store.list_conversations()
        self.assertEqual([summary.id for summary in summaries], [second.id, first.id])

    def test_delete_removes_index_entry_and_file(self) -> None:
        conversation = self.store.create("claude", "ask", ())
        path = self.store._conversation_path(conversation.id)
        self.assertTrue(path.exists())
        self.assertTrue(self.store.delete(conversation.id))
        self.assertFalse(path.exists())
        self.assertIsNone(self.store.get(conversation.id))

    def test_delete_unknown_conversation_returns_false(self) -> None:
        self.assertFalse(self.store.delete("nope"))

    def test_retention_evicts_oldest_first(self) -> None:
        ids = []
        for _ in range(5):
            conversation = self.store.create("claude", "ask", ())
            ids.append(conversation.id)
            time.sleep(0.01)
        summaries = self.store.list_conversations()
        self.assertEqual(len(summaries), 3)
        kept_ids = {summary.id for summary in summaries}
        self.assertEqual(kept_ids, set(ids[-3:]))
        for evicted_id in ids[:2]:
            self.assertIsNone(self.store.get(evicted_id))

    def test_long_turn_text_is_truncated_with_a_marker(self) -> None:
        conversation = self.store.create("claude", "ask", ())
        huge = "x" * (MAX_TURN_TEXT_BYTES + 1000)
        self.store.append_turn(conversation.id, Turn("assistant", huge))
        loaded = self.store.get(conversation.id)
        stored_text = loaded.turns[0].text
        marker_bytes = len(_TRUNCATION_MARKER.encode("utf-8"))
        self.assertLessEqual(len(stored_text.encode("utf-8")), MAX_TURN_TEXT_BYTES + marker_bytes)
        self.assertTrue(stored_text.endswith("[truncated]"))

    def test_provider_session_id_round_trips(self) -> None:
        conversation = self.store.create("claude", "ask", ())
        self.store.set_provider_session_id(conversation.id, "sess-42")
        loaded = self.store.get(conversation.id)
        self.assertEqual(loaded.provider_session_id, "sess-42")

    def test_a_truncated_partial_last_line_is_discarded_not_fatal(self) -> None:
        conversation = self.store.create("claude", "ask", ())
        self.store.append_turn(conversation.id, Turn("user", "hello"))
        path = self.store._conversation_path(conversation.id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write('{"role":"assistant","text":"cut off mid-wri')  # no trailing newline, malformed
        loaded = self.store.get(conversation.id)
        self.assertEqual(len(loaded.turns), 1)
        self.assertEqual(loaded.turns[0].text, "hello")

    def test_conversation_id_path_traversal_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.store._conversation_path("../../etc/passwd")
        with self.assertRaises(ValueError):
            self.store._conversation_path("")

    def test_stored_turn_json_has_only_role_text_at_fields(self) -> None:
        # Storage never adds fields beyond role/text/at itself; callers are
        # responsible for never constructing a Turn from secret-bearing data
        # (see docs/security.md) — this locks in that the schema stays that
        # narrow rather than accidentally growing an extra column later.
        conversation = self.store.create("claude", "ask", ())
        self.store.append_turn(conversation.id, Turn("user", "hello"))
        raw = self.store._conversation_path(conversation.id).read_text(encoding="utf-8")
        for line in raw.splitlines():
            value = json.loads(line)
            self.assertEqual(set(value.keys()), {"role", "text", "at"})


if __name__ == "__main__":
    unittest.main()
