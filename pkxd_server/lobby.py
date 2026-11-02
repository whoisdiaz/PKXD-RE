"""The recovered POST /lobby/allocation contract, without gameplay/auth services."""
import json
import logging
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from . import SUPPORTED_PROTOCOL, TARGET_APP_VERSION

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


def allocate(payload, destination):
    """Return an HTTP status and a PlayerAllocationResponse-compatible object.

    The native request carries a protocol version, not an APK appVersion. Builds
    sharing protocol 0.2.49 cannot be distinguished by this request alone.
    userToken is treated as opaque input here; authentication is a later stage.
    """
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
    if protocol != SUPPORTED_PROTOCOL:
        # The recovered client first requires a nonempty 2xx HTTP response, then
        # reads successful/failureReason. HTTP 426 would bypass that branch.
        return 200, failure(PROTOCOL_MISMATCH, f"Supported game protocol: {SUPPORTED_PROTOCOL}.")
    if private or "destinationRoomId" in payload or "destinationUserId" in payload:
        return 400, failure("UNSUPPORTED_ALLOCATION", "This stage supports default-world allocation only.")
    return 200, {
        "successful": True,
        "failureReason": "",
        "failureDescription": "",
        "gameServerId": f"local-{TARGET_APP_VERSION}",
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

    def __init__(self, address, destination):
        self.destination = destination
        super().__init__(address, LobbyHandler)


class LobbyHandler(BaseHTTPRequestHandler):
    server_version = "PKXDLocalLobby/0.1"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_request(self, code="-", size="-"):
        # Do not record tokens, bodies, or query parameters.
        LOG.info("%s status=%s", self.command, code)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if urlsplit(self.path).path != "/health":
            self.send_json(404, failure("NOT_FOUND", "Unknown endpoint."))
            return
        # Local diagnostic endpoint, not a recovered game API.
        self.send_json(200, {
            "status": "ok",
            "targetAppVersion": TARGET_APP_VERSION,
            "acceptedGameServerProtocolVersion": SUPPORTED_PROTOCOL,
            "gameTransportImplemented": False,
        })

    def do_POST(self):
        if urlsplit(self.path).path != ALLOCATION_PATH:
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
        status, response = allocate(payload, self.server.destination)
        self.send_json(status, response)
