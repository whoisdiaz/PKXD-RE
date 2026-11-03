import argparse
import logging
import sqlite3
import threading
from contextlib import ExitStack
from pathlib import Path

from . import TARGET_APP_VERSION
from .accounts import AccountStore
from .game import GameServer
from .lobby import GameDestination, LobbyServer
from .version_policy import DEFAULT_CONFIG, load_policy


def main():
    parser = argparse.ArgumentParser(description="Local accounts, characters and world sessions for PK XD 1.38.4")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind address (default: loopback)")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port")
    parser.add_argument("--game-host", default="127.0.0.1", help="Game destination advertised to the client")
    parser.add_argument("--game-port", type=int, default=7000, help="TCP game port (default: 7000)")
    parser.add_argument("--game-bind", help="TCP bind address (default: same as --host)")
    parser.add_argument("--game-udp-port", type=int, default=0, help="Game UDP port; 0 omits UDP")
    parser.add_argument("--version-config", default=DEFAULT_CONFIG, help="Version permission JSON file")
    parser.add_argument("--database", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "players.sqlite3",
                        help="Persistent local account/character database")
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("HTTP port must be between 0 and 65535")
    if args.game_udp_port != 0:
        parser.error("This stage implements TCP only; --game-udp-port must be 0")
    try:
        destination = GameDestination(args.game_host, args.game_port, args.game_udp_port)
        policy = load_policy(args.version_config, TARGET_APP_VERSION)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    with ExitStack() as stack:
        try:
            store = AccountStore(args.database)
            game = stack.enter_context(GameServer((args.game_bind or args.host, args.game_port), store, policy))
            server = stack.enter_context(LobbyServer((args.host, args.port), destination, policy, store=store, game=game))
        except (OSError, ValueError, sqlite3.Error) as error:
            parser.exit(1, f"Could not start local services: {error}\n")
        logging.info("PK XD %s: version %s; game protocol %s", policy.app_version,
                     "enabled" if policy.enabled else "disabled", policy.protocol)
        logging.info("Lobby HTTP: %s:%s", *server.server_address[:2])
        logging.info("Game TCP: %s:%s (local world room)", *game.server_address[:2])
        logging.info("Local accounts and characters: %s", store.path)
        logging.info("Startup services: server time, empty local catalogs and initial lists")
        logging.info("Entry queries: fruit count, matchmaking state, seasonal time and referral information")
        logging.info("World: single-player rooms, movement/layers, interaction cache, vehicle queries")
        logging.info("Client metadata must redirect BOTH accounts and lobby to this server")
        game_thread = threading.Thread(target=game.serve_forever, daemon=True)
        game_thread.start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            game.shutdown()
            game_thread.join(timeout=5)


if __name__ == "__main__":
    main()
