import hashlib
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from pkxd_server.accounts import AccountStore, AccountError, SIGN_UP
from pkxd_server.avatar_defaults import DEFAULT_EQUIPPED_ITEMS, STARTER_ITEM_IDS
from pkxd_server.inventory import favorites_response


class InventoryPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "players.sqlite3"

    def test_native_default_slots_and_unique_local_grant(self):
        self.assertEqual(STARTER_ITEM_IDS, (5, 13, 15, 16, 17, 59, 272, 273, 4636))
        self.assertEqual(DEFAULT_EQUIPPED_ITEMS,
                         (0, 0, 0, 0, 4636, 16, 5, 13, 272, 15, 273, 17, 17, 59, 59, 0, 0, 0))
        store = AccountStore(self.path)
        store.post(SIGN_UP, {})
        with store.connect() as db:
            player_id = db.execute("SELECT id FROM players").fetchone()[0]
        self.assertEqual(store.inventory(player_id), {item: 1 for item in STARTER_ITEM_IDS})
        AccountStore(self.path)
        self.assertEqual(store.inventory(player_id)[17], 1)  # Two hand slots share one item.
        self.assertEqual(store.inventory(player_id)[59], 1)  # Two foot slots share one item.

    def test_old_database_migrates_without_losing_session_name_or_appearance(self):
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE players (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT UNIQUE NOT NULL,
                    nickname TEXT NOT NULL, nickname_key TEXT UNIQUE NOT NULL, created_at INTEGER NOT NULL,
                    character_created INTEGER NOT NULL DEFAULT 0, cosmetics TEXT NOT NULL DEFAULT '{}',
                    terms TEXT NOT NULL DEFAULT '', ads_consent INTEGER NOT NULL DEFAULT 0,
                    open_chat INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE tokens (digest TEXT PRIMARY KEY, kind TEXT NOT NULL,
                    player_id INTEGER NOT NULL REFERENCES players(id), session_id TEXT NOT NULL,
                    auth_session_id TEXT NOT NULL, expires_at INTEGER NOT NULL);
            """)
            db.execute("INSERT INTO players (id,user_id,nickname,nickname_key,created_at,character_created,cosmetics,terms) VALUES (1,?,?,?,?,?,?,?)",
                       ("legacy-user", "Ana", "ana", 1700000000000, 1, json.dumps({"j": "05102030"}), "explicit-old-terms"))
            db.execute("INSERT INTO tokens VALUES (?,?,?,?,?,?)",
                       (hashlib.sha256(b"legacy-user-token").hexdigest(), "user", 1, "session", "auth", int(time.time()) + 3600))
        store = AccountStore(self.path)
        player = store.user("legacy-user-token")
        self.assertEqual((player["user_id"], player["nickname"], player["character_created"]), ("legacy-user", "Ana", 1))
        self.assertEqual(json.loads(player["cosmetics"]), {"j": "05102030"})
        self.assertEqual(player["terms"], "explicit-old-terms")
        self.assertEqual(store.inventory(1), {item: 1 for item in STARTER_ITEM_IDS})
        with store.connect() as db:
            db.execute("UPDATE player_inventory SET quantity=7 WHERE player_id=1 AND item_id=5")
        store.update_favorites(1, [5], [])
        reopened = AccountStore(self.path)
        self.assertEqual(reopened.inventory(1)[5], 7)
        self.assertEqual(reopened.update_favorites(1, [], []), [5])
        self.assertEqual(reopened.user("legacy-user-token")["nickname"], "Ana")

    def test_initial_grant_is_not_repeated_after_inventory_is_emptied(self):
        store = AccountStore(self.path)
        store.post(SIGN_UP, {})
        with store.connect() as db:
            player_id = db.execute("SELECT id FROM players").fetchone()[0]
            db.execute("DELETE FROM player_inventory WHERE player_id=?", (player_id,))
        reopened = AccountStore(self.path)
        self.assertEqual(reopened.inventory(player_id), {})
        with reopened.connect() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM inventory_seeds WHERE player_id=?", (player_id,)).fetchone()[0], 1)

    def test_unmarked_custom_inventory_is_preserved_during_upgrade(self):
        store = AccountStore(self.path)
        store.post(SIGN_UP, {})
        with store.connect() as db:
            player_id = db.execute("SELECT id FROM players").fetchone()[0]
            db.execute("DELETE FROM inventory_seeds WHERE player_id=?", (player_id,))
            db.execute("DELETE FROM player_inventory WHERE player_id=?", (player_id,))
            db.execute("INSERT INTO player_inventory VALUES (?, ?, ?)", (player_id, 999, 3))
        reopened = AccountStore(self.path)
        self.assertEqual(reopened.inventory(player_id), {999: 3})

    def test_favorites_require_owned_items_and_survive_restart(self):
        store = AccountStore(self.path)
        store.post(SIGN_UP, {})
        with store.connect() as db:
            player_id = db.execute("SELECT id FROM players").fetchone()[0]
        self.assertEqual(store.update_favorites(player_id, [], []), [])
        self.assertEqual(store.update_favorites(player_id, [5, 16, 5], []), [5, 16])
        for added, removed in (([123456], []), ([5], [5]), ([-1], [])):
            with self.assertRaises(AccountError):
                store.update_favorites(player_id, added, removed)
        self.assertEqual(AccountStore(self.path).update_favorites(player_id, [], []), [5, 16])
        self.assertEqual(store.update_favorites(player_id, [], [5]), [16])
        self.assertNotIn(123456, store.inventory(player_id))

    def test_empty_favorite_success_requires_a_present_oneof_message(self):
        self.assertEqual(favorites_response([]), bytes.fromhex("08021200"))
        self.assertEqual(favorites_response([5, 16]), bytes.fromhex("0802120408050810"))


if __name__ == "__main__":
    unittest.main()
