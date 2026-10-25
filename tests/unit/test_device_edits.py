"""SQLite unit tests with an isolated minimal schema and no network access."""

import sqlite3
import unittest

from nettracker.db.device_edits import mark_known, update_identity
from nettracker.errors import DatabaseError


class DeviceEditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:", isolation_level=None)
        self.conn.execute(
            "CREATE TABLE devices (id INTEGER PRIMARY KEY, alias TEXT, device_type TEXT, "
            "status TEXT NOT NULL, merged_into INTEGER, hostname TEXT)"
        )
        self.conn.execute("INSERT INTO devices VALUES (1, NULL, NULL, 'to_confirm', NULL, 'phone')")

    def tearDown(self) -> None:
        self.conn.close()

    def test_identity_and_blank_fallback(self) -> None:
        update_identity(self.conn, 1, alias="  Téléphone test  ", device_type="phone")
        row = self.conn.execute("SELECT alias, device_type FROM devices").fetchone()
        self.assertEqual(row, ("Téléphone test", "phone"))
        update_identity(self.conn, 1, alias=" ", device_type="")
        row = self.conn.execute("SELECT alias, device_type, hostname FROM devices").fetchone()
        self.assertEqual(row, (None, None, "phone"))

    def test_validation_is_atomic(self) -> None:
        for alias, kind in [("a" * 121, "phone"), ("bad\nname", "phone"), ("name", "invalid")]:
            with self.subTest(alias=alias, kind=kind), self.assertRaises(ValueError):
                update_identity(self.conn, 1, alias=alias, device_type=kind)
        self.assertIsNone(self.conn.execute("SELECT alias FROM devices").fetchone()[0])

    def test_known_is_idempotent(self) -> None:
        mark_known(self.conn, 1)
        mark_known(self.conn, 1)
        self.assertEqual(self.conn.execute("SELECT status FROM devices").fetchone()[0], "known")

    def test_ignored_and_merged_are_preserved(self) -> None:
        self.conn.execute("UPDATE devices SET status = 'ignored'")
        with self.assertRaises(ValueError):
            mark_known(self.conn, 1)
        self.conn.execute("UPDATE devices SET merged_into = 2")
        with self.assertRaises(ValueError):
            update_identity(self.conn, 1, alias="name", device_type="phone")

    def test_missing_and_invalid_ids(self) -> None:
        with self.assertRaises(LookupError):
            mark_known(self.conn, 99)
        for device_id in (0, -1, True):
            with self.subTest(device_id=device_id), self.assertRaises(ValueError):
                mark_known(self.conn, device_id)
        self.assertFalse(self.conn.in_transaction)

    def test_outer_transaction_can_rollback(self) -> None:
        self.conn.execute("BEGIN")
        update_identity(self.conn, 1, alias="name", device_type="nas")
        self.conn.execute("ROLLBACK")
        self.assertIsNone(self.conn.execute("SELECT alias FROM devices").fetchone()[0])

    def test_failure_preserves_outer_transaction(self) -> None:
        self.conn.execute("BEGIN")
        self.conn.execute("UPDATE devices SET hostname = 'changed'")
        with self.assertRaises(LookupError):
            mark_known(self.conn, 99)
        self.assertTrue(self.conn.in_transaction)
        self.conn.execute("COMMIT")
        self.assertEqual(self.conn.execute("SELECT hostname FROM devices").fetchone()[0], "changed")

    def test_readonly_database_rejects_edits(self) -> None:
        self.conn.execute("PRAGMA query_only = ON")
        with self.assertRaises(DatabaseError):
            mark_known(self.conn, 1)
        self.assertFalse(self.conn.in_transaction)

    def test_sql_payload_is_only_text(self) -> None:
        payload = "'; DROP TABLE devices; --"
        update_identity(self.conn, 1, alias=payload, device_type="other")
        self.assertEqual(self.conn.execute("SELECT alias FROM devices").fetchone()[0], payload)
