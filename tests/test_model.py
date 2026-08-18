from __future__ import annotations

import unittest
import uuid

from everything.model import (
    SnapshotRegistry,
    TokenCodec,
    TokenError,
    Thing,
    dedupe_things,
    identity_component,
    stable_id,
    thing_ui_uuid,
)


def thing(identifier: str, activation: dict | None = None) -> Thing:
    return Thing(
        id=identifier,
        kind="window",
        provider="Test",
        title="Same title",
        activation=activation or {"native": identifier},
    )


class IdentityTests(unittest.TestCase):
    def test_identity_components_do_not_collide(self) -> None:
        self.assertNotEqual(stable_id("test", "a/b", "c"), stable_id("test", "a", "b/c"))
        self.assertEqual(identity_component("same title"), "same%20title")
        self.assertIn("%25", identity_component("100%"))

    def test_duplicate_titles_keep_distinct_native_ids(self) -> None:
        rows = dedupe_things([thing("test:native-1"), thing("test:native-2")])
        self.assertEqual([row.id for row in rows], ["test:native-1", "test:native-2"])

    def test_conflicting_duplicate_ids_are_not_silently_dropped(self) -> None:
        rows = dedupe_things(
            [thing("test:collision", {"native": 1}), thing("test:collision", {"native": 2})]
        )
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0].id, rows[1].id)

    def test_equal_duplicate_rows_merge_badges(self) -> None:
        first = thing("test:one", {"native": 1})
        first.badges = ["One"]
        second = thing("test:one", {"native": 1})
        second.badges = ["Two"]
        self.assertEqual(dedupe_things([first, second])[0].badges, ["One", "Two"])

    def test_ui_uuid_is_deterministic_and_trait_scoped(self) -> None:
        value = thing_ui_uuid("Test", "window", "test:native-1")
        self.assertEqual(value, thing_ui_uuid("Test", "window", "test:native-1"))
        self.assertNotEqual(value, thing_ui_uuid("Test", "window", "test:native-2"))
        self.assertNotEqual(value, thing_ui_uuid("Test", "browser-tab", "test:native-1"))
        self.assertEqual(uuid.UUID(value).version, 5)

    def test_public_item_contains_its_ui_uuid(self) -> None:
        row = thing("test:native-1")
        public = row.public("opaque")
        self.assertEqual(public["uiUuid"], thing_ui_uuid(row.provider, row.kind, row.id))


class TokenTests(unittest.TestCase):
    def test_tokens_are_authenticated_and_process_local(self) -> None:
        codec = TokenCodec(b"a" * 32)
        token = codec.encode({"provider": "test", "id": "test:1", "generation": 1})
        self.assertEqual(codec.decode(token)["id"], "test:1")
        with self.assertRaises(TokenError):
            TokenCodec(b"b" * 32).decode(token)

    def test_snapshot_generation_rejects_stale_token(self) -> None:
        registry = SnapshotRegistry(TokenCodec(b"x" * 32))
        first = registry.publish("test", [thing("test:1")])[0]
        reference = registry.decode_reference("test:1", first["activationToken"])
        self.assertTrue(registry.token_is_current(reference))
        registry.publish("test", [thing("test:1")])
        self.assertFalse(registry.token_is_current(reference))

    def test_token_cannot_be_retargeted(self) -> None:
        registry = SnapshotRegistry(TokenCodec(b"y" * 32))
        row = registry.publish("test", [thing("test:1")])[0]
        with self.assertRaises(TokenError):
            registry.decode_reference("test:2", row["activationToken"])


if __name__ == "__main__":
    unittest.main()
