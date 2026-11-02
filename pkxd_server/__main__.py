import argparse
import logging

from . import SUPPORTED_PROTOCOL, TARGET_APP_VERSION
from .lobby import GameDestination, LobbyServer


def main():
    parser = argparse.ArgumentParser(description="Local allocation lobby for PK XD 1.38.4 / protocol 0.2.49")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default: loopback)")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port")
    parser.add_argument("--game-host", default="127.0.0.1", help="Game destination advertised to the client")
    parser.add_argument("--game-port", type=int, required=True, help="TCP port of the game service (not started here)")
    parser.add_argument("--game-udp-port", type=int, default=0, help="Game UDP port; 0 omits UDP")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("HTTP port must be between 0 and 65535")
    try:
        destination = GameDestination(args.game_host, args.game_port, args.game_udp_port)
    except ValueError as error:
        parser.error(str(error))
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        server = LobbyServer((args.host, args.port), destination)
    except OSError as error:
        parser.exit(1, f"Could not start the lobby: {error}\n")
    with server:
        logging.info("PK XD %s: accepting game protocol %s", TARGET_APP_VERSION, SUPPORTED_PROTOCOL)
        logging.info("Lobby HTTP: %s:%s", *server.server_address[:2])
        logging.info("Advertised game destination: %s:%s (game service is a separate stage)", destination.host, destination.tcp_port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
