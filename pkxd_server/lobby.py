"""HTTP allocation lobby and local anonymous account endpoints."""
import json
import logging
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from .accounts import AccountError, AUTH, IDENTITIES, POST_ROUTES
from .version_policy import VersionPolicy

LOG = logging.getLogger(__name__)
MAX_BODY_BYTES = 64 * 1024
ALLOCATION_PATH = "/lobby/allocation"
PROTOCOL_MISMATCH = "GAME_SERVER_PROTOCOL_VERSION_MISMATCH"


@dataclass(frozen=True)
class GameDestination:
    """Destination advertised to the client; no game listener is started here."""

    host: str
    tcp_port: int
    udp_port: int = 0

    def __post_init__(self):
        if not self.host or any(c.isspace() for c in self.host) or "/" in self.host:
            raise ValueError("game host must be an IP address or hostname, without a URL scheme")
        if self.host in ("0.0.0.0", "::"):
            raise ValueError("game host must be a destination address, not a wildcard bind address")
        if type(self.tcp_port) is not int or not 1 <= self.tcp_port <= 65535:
            raise ValueError("game TCP port must be between 1 and 65535")
        if type(self.udp_port) is not int or not 0 <= self.udp_port <= 65535:
            raise ValueError("game UDP port must be 0 (disabled) or between 1 and 65535")


def failure(reason, description):
    return {"successful": False, "failureReason": reason, "failureDescription": description}


def allocate(payload, destination, policy=None):
    """Return an HTTP status and a PlayerAllocationResponse-compatible object.

    The native request carries a protocol version, not an APK appVersion. Builds
    sharing protocol 0.2.49 cannot be distinguished by this request alone.
    userToken is treated as opaque input here; authentication is a later stage.
    """
    if policy is None:
        policy = VersionPolicy()
    if not isinstance(payload, dict):
        return 400, failure("INVALID_REQUEST", "Expected a JSON object.")
    token = payload.get("userToken")
    protocol = payload.get("gameServerProtocolVersion")
    private = payload.get("isPrivate")
    if not isinstance(token, str) or not token or len(token) > 8192:
        return 400, failure("INVALID_REQUEST", "Expected a nonempty userToken string.")
    if not isinstance(protocol, str) or not protocol or len(protocol) > 64:
        return 400, failure("INVALID_REQUEST", "Expected a gameServerProtocolVersion string.")
    if type(private) is not bool:
        return 400, failure("INVALID_REQUEST", "Expected an isPrivate boolean.")
    if not policy.enabled or protocol != policy.protocol:
        # The recovered client first requires a nonempty 2xx HTTP response, then
        # reads successful/failureReason. HTTP 426 would bypass that branch.
        description = (f"Supported game protocol: {policy.protocol}." if policy.enabled
                       else "This deployment has disabled the configured version.")
        return 200, failure(PROTOCOL_MISMATCH, description)
    if private or "destinationRoomId" in payload or "destinationUserId" in payload:
        return 400, failure("UNSUPPORTED_ALLOCATION", "This stage supports default-world allocation only.")
    return 200, {
        "successful": True,
        "failureReason": "",
        "failureDescription": "",
        "gameServerId": f"local-{policy.app_version}",
        "gameServerAddress": destination.host,
        "gameServerHosts": [destination.host],
        "gameServerPort": destination.tcp_port,
        "gameServerUdpPort": destination.udp_port,
        "gameServerEngine": "ToxicBird",
        "gameServerType": "DEFAULT",
        "gameServerOwnerId": "",
    }


class LobbyServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, destination, policy=None, *, store=None, game=None):
        self.destination = destination
        self.policy = policy if policy is not None else VersionPolicy()
        self.store, self.game = store, game
        super().__init__(address, LobbyHandler)


class LobbyHandler(BaseHTTPRequestHandler):
    server_version = "PKXDLocal/0.2"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_request(self, code="-", size="-"):
        # Do not record tokens, bodies, or query parameters.
        path = self.path.partition("?")[0]
        route = path if path in (ALLOCATION_PATH, "/health", IDENTITIES, *POST_ROUTES) else "unknown-endpoint"
        if path.startswith(AUTH + "/") and self.server.store is not None:
            route = AUTH + "/<session>"
        LOG.info("%s %s status=%s", self.command, route, code)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def account_error(self, error):
        # FasterErrorResponse fields recovered from the client's DTO.
        self.send_json(error.status, {"statusCode": error.status, "status": error.code,
                                      "description": str(error)})

    def do_GET(self):
        path = urlsplit(self.path).path
        if self.server.store is not None and (path == IDENTITIES or path.startswith(AUTH + "/")):
            try:
                if path == IDENTITIES:
                    authorization = self.headers.get("Authorization", "")
                    token = authorization[7:] if authorization.startswith("Bearer ") else ""
                    response = self.server.store.get_identities(token)
                else:
                    response = self.server.store.get_session(path[len(AUTH) + 1:])
            except AccountError as error:
                self.account_error(error)
            else:
                self.send_json(200, response)
            return
        if path != "/health":
            self.send_json(404, failure("NOT_FOUND", "Unknown endpoint."))
            return
        # Local diagnostic endpoint, not a recovered game API.
        self.send_json(200, {
            "status": "ok",
            "targetAppVersion": self.server.policy.app_version,
            "versionEnabled": self.server.policy.enabled,
            "acceptedGameServerProtocolVersion": self.server.policy.protocol if self.server.policy.enabled else None,
            "gameTransportImplemented": self.server.game is not None,
            "anonymousAccountsImplemented": self.server.store is not None,
            "characterBootstrapImplemented": self.server.game is not None,
            "worldImplemented": False,
        })

    def do_POST(self):
        path = urlsplit(self.path).path
        account_route = path in POST_ROUTES and self.server.store is not None
        if path != ALLOCATION_PATH and not account_route:
            self.send_json(404, failure("NOT_FOUND", "Unknown endpoint."))
            return
        if self.headers.get("Transfer-Encoding") is not None:
            self.send_json(400, failure("INVALID_REQUEST", "Transfer-Encoding is not supported."))
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json(415, failure("INVALID_REQUEST", "Expected Content-Type application/json."))
            return
        values = self.headers.get_all("Content-Length", [])
        if not values:
            self.send_json(411, failure("INVALID_REQUEST", "Content-Length is required."))
            return
        if len(values) != 1 or not values[0].isascii() or not values[0].isdecimal():
            self.send_json(400, failure("INVALID_REQUEST", "Invalid Content-Length."))
            return
        size = int(values[0])
        if size > MAX_BODY_BYTES:
            self.send_json(413, failure("INVALID_REQUEST", "Request body is too large."))
            return
        try:
            raw = self.rfile.read(size)
            if len(raw) != size:
                raise ValueError("Incomplete request body")
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self.send_json(400, failure("INVALID_REQUEST", "Invalid UTF-8 JSON body."))
            return
        except TimeoutError:
            self.send_json(408, failure("INVALID_REQUEST", "Request body timed out."))
            return
        try:
            if account_route:
                response = self.server.store.post(path, payload)
                status = 200
            else:
                status, response = allocate(payload, self.server.destination, self.server.policy)
                if response.get("successful") and self.server.store is not None:
                    self.server.store.user(payload["userToken"])
        except AccountError as error:
            if account_route:
                self.account_error(error)
                return
            status, response = error.status, failure(error.code, str(error))
        self.send_json(status, response)
