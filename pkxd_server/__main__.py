import argparse
import logging

from . import TARGET_APP_VERSION
from .lobby import GameDestination, LobbyServer
from .version_policy import DEFAULT_CONFIG, load_policy


def main():
    parser = argparse.ArgumentParser(description="Local allocation lobby for PK XD 1.38.4 / protocol 0.2.49")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default: loopback)")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port")
    parser.add_argument("--game-host", default="127.0.0.1", help="Game destination advertised to the client")
    parser.add_argument("--game-port", type=int, default=7000, help="TCP port of the game service (default: 7000; not started here)")
    parser.add_argument("--game-udp-port", type=int, default=0, help="Game UDP port; 0 omits UDP")
    parser.add_argument("--version-config", default=DEFAULT_CONFIG, help="Version permission JSON file")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("HTTP port must be between 0 and 65535")
    try:
        destination = GameDestination(args.game_host, args.game_port, args.game_udp_port)
        policy = load_policy(args.version_config, TARGET_APP_VERSION)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        server = LobbyServer((args.host, args.port), destination, policy)
    except OSError as error:
        parser.exit(1, f"Could not start the lobby: {error}\n")
    with server:
        logging.info("PK XD %s: version %s; game protocol %s", policy.app_version,
                     "enabled" if policy.enabled else "disabled", policy.protocol)
        logging.info("Lobby HTTP: %s:%s", *server.server_address[:2])
        logging.info("Advertised game destination: %s:%s (game service is a separate stage)", destination.host, destination.tcp_port)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
