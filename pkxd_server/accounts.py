"""Local anonymous identities and character persistence. No upstream services."""
import hashlib
import json
import secrets
import sqlite3
import time
import unicodedata
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SIGN_UP = "/v1/identity/anonymous/sign-up"
AUTH = "/v1/auth/sessions"
USER = "/v1/users/sessions"
REISSUE = AUTH + "/pkxd/token"
IDENTITIES = "/v1/users/identities"
POST_ROUTES = {SIGN_UP, AUTH, USER, REISSUE}


class AccountError(ValueError):
    def __init__(self, code, message, status=400):
        super().__init__(message)
        self.code, self.status = code, status


class AccountStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS players (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT UNIQUE NOT NULL,
                    nickname TEXT NOT NULL,
                    nickname_key TEXT UNIQUE NOT NULL,
                    created_at INTEGER NOT NULL,
                    character_created INTEGER NOT NULL DEFAULT 0,
                    cosmetics TEXT NOT NULL DEFAULT '{}',
                    terms TEXT NOT NULL DEFAULT '',
                    ads_consent INTEGER NOT NULL DEFAULT 0,
                    open_chat INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS tokens (
                    digest TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    player_id INTEGER NOT NULL REFERENCES players(id),
                    session_id TEXT NOT NULL,
                    auth_session_id TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def issue(db, kind, player_id, auth_session_id=""):
        token = secrets.token_urlsafe(32)
        session = str(uuid.uuid4())
        # An anonymous identity is the persistent credential on this local server.
        lifetime = {"identity": 10 * 365 * 86400, "auth": 30 * 86400, "user": 7 * 86400}[kind]
        db.execute("DELETE FROM tokens WHERE expires_at <= ?", (int(time.time()),))
        db.execute("INSERT INTO tokens VALUES (?, ?, ?, ?, ?, ?)",
                   (hashlib.sha256(token.encode()).hexdigest(), kind, player_id,
                    session, auth_session_id, int(time.time()) + lifetime))
        return token, session

    @staticmethod
    def resolve(db, token, kind):
        if not isinstance(token, str) or not 1 <= len(token) <= 8192:
            raise AccountError("UNAUTHORIZED", "A local session token is required.", 401)
        try:
            digest = hashlib.sha256(token.encode()).hexdigest()
        except UnicodeEncodeError as error:
            raise AccountError("UNAUTHORIZED", "Invalid local session encoding.", 401) from error
        row = db.execute("""SELECT p.*, t.session_id, t.auth_session_id FROM tokens t
            JOIN players p ON p.id=t.player_id
            WHERE digest=? AND kind=? AND expires_at>?""", (digest, kind, int(time.time()))).fetchone()
        if row is None:
            raise AccountError("UNAUTHORIZED", "Invalid or expired local session.", 401)
        return dict(row)

    def user(self, token):
        with self.connect() as db:
            return self.resolve(db, token, "user")

    def player(self, player_id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
            if row is None:
                raise AccountError("NOT_FOUND", "Local player not found.", 404)
            return dict(row)

    def post(self, path, payload):
        if not isinstance(payload, dict):
            raise AccountError("INVALID_REQUEST", "Expected a JSON object.")
        with self.connect() as db:
            if path == SIGN_UP:
                user_id = str(uuid.uuid4())
                provisional = "Jogador-" + uuid.uuid4().hex[:12]
                cursor = db.execute("""INSERT INTO players
                    (user_id,nickname,nickname_key,created_at) VALUES (?,?,?,?)""",
                                    (user_id, provisional, provisional.casefold(), int(time.time() * 1000)))
                token, _ = self.issue(db, "identity", cursor.lastrowid)
                return {"token": token}
            if path == AUTH:
                credential = payload.get("credentials")
                if (payload.get("identityProvider") != "FASTER" or not isinstance(credential, dict)
                        or credential.get("type") != "TOKEN"):
                    raise AccountError("UNSUPPORTED_IDENTITY", "Only local anonymous TOKEN credentials are supported.")
                player = self.resolve(db, credential.get("token"), "identity")
                token, session = self.issue(db, "auth", player["id"])
                return {"userId": player["user_id"], "sessionId": session,
                        "identity": player["user_id"], "identityType": "anonymous", "authToken": token}
            player = self.resolve(db, payload.get("authToken"), "auth")
            if path == USER:
                token, session = self.issue(db, "user", player["id"], player["session_id"])
                return {"userId": player["user_id"], "sessionId": session,
                        "authSessionId": player["session_id"], "userToken": token, "countryByIp": "BR"}
            if path == REISSUE:
                # Keep the previous credential valid until expiry, so retries cannot lose the account.
                token, _ = self.issue(db, "auth", player["id"])
                return {"authToken": token}
        raise AccountError("NOT_FOUND", "Unknown account endpoint.", 404)

    def get_session(self, token):
        with self.connect() as db:
            player = self.resolve(db, token, "auth")
            return {"userId": player["user_id"], "identityType": "anonymous", "identityKey": player["user_id"]}

    def get_identities(self, token):
        player = self.user(token)
        linked_at = datetime.fromtimestamp(player["created_at"] / 1000, timezone.utc).isoformat(timespec="milliseconds")
        return {"response": [{"type": "anonymous", "key": player["user_id"],
                              "linkedAt": linked_at.replace("+00:00", "Z"), "provider": "FASTER",
                              "validationStatus": ""}]}

    def set_name(self, player_id, name):
        name = unicodedata.normalize("NFC", name).strip()
        if not 2 <= len(name) <= 24 or any(unicodedata.category(c).startswith("C") for c in name):
            raise AccountError("INVALID_NAME", "Use de 2 a 24 caracteres visíveis no nome.")
        with self.connect() as db:
            current = db.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
            if current["character_created"] and current["nickname"] != name:
                raise AccountError("CHARACTER_EXISTS", "O personagem já foi criado. Troca de nome será outra etapa.")
            try:
                db.execute("UPDATE players SET nickname=?, nickname_key=?, character_created=1 WHERE id=?",
                           (name, name.casefold(), player_id))
            except sqlite3.IntegrityError as error:
                raise AccountError("NAME_IN_USE", "Este nome já está em uso no servidor local.") from error
        return name

    def save_cosmetic(self, player_id, key, value):
        self.save_cosmetics(player_id, {key: value})

    def save_cosmetics(self, player_id, values):
        with self.connect() as db:
            row = db.execute("SELECT cosmetics FROM players WHERE id=?", (player_id,)).fetchone()
            cosmetics = json.loads(row[0])
            cosmetics.update({key: value.hex() for key, value in values.items()})
            db.execute("UPDATE players SET cosmetics=? WHERE id=?", (json.dumps(cosmetics), player_id))

    def set_legal(self, player_id, terms, consent):
        if len(terms) > 64:
            raise AccountError("INVALID_TERMS", "Terms version is too long.")
        with self.connect() as db:
            db.execute("UPDATE players SET terms=?, ads_consent=? WHERE id=?", (terms, int(consent), player_id))

    def set_open_chat(self, player_id, enabled):
        with self.connect() as db:
            db.execute("UPDATE players SET open_chat=? WHERE id=?", (int(enabled), player_id))
