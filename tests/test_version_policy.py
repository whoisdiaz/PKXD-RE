import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from pkxd_server.lobby import GameDestination, LobbyServer, allocate
from pkxd_server.version_policy import VersionPolicy, load_policy


class VersionPermissionTests(unittest.TestCase):
    def load(self, value, app_version="1.38.4"):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "versions.json"
            path.write_text(json.dumps(value))
            return load_policy(path, app_version)

    def request_payload(self):
        return {"userToken": "permission-test", "gameServerProtocolVersion": "0.2.49", "isPrivate": False}

    def test_shipped_permission_enables_the_requested_version(self):
        policy = load_policy()
        self.assertEqual(policy.app_version, "1.38.4")
        self.assertEqual(policy.protocol, "0.2.49")
        self.assertIs(policy.enabled, True)

    def test_disabled_version_rejects_its_matching_protocol(self):
        policy = self.load({"1.38.4": {"enabled": False, "gameServerProtocolVersion": "0.2.49"}})
        status, response = allocate(self.request_payload(), GameDestination("127.0.0.1", 7000), policy)
        self.assertEqual(status, 200)
        self.assertIs(response["successful"], False)
        self.assertEqual(response["failureReason"], "GAME_SERVER_PROTOCOL_VERSION_MISMATCH")

    def test_configuration_controls_the_gate_instead_of_the_default_constant(self):
        policy = self.load({"1.38.4": {"enabled": True, "gameServerProtocolVersion": "0.2.48"}})
        status, response = allocate(self.request_payload(), GameDestination("127.0.0.1", 7000), policy)
        self.assertEqual(status, 200)
        self.assertIs(response["successful"], False)

    def test_unknown_version_has_no_implicit_permission(self):
        with self.assertRaisesRegex(ValueError, "No permission"):
            self.load({"1.38.4": {"enabled": True, "gameServerProtocolVersion": "0.2.49"}}, "1.38.5")

    def test_ambiguous_enabled_values_are_rejected(self):
        for enabled in ["false", "true", 1, 0, None]:
            with self.subTest(enabled=enabled), self.assertRaises(ValueError):
                self.load({"1.38.4": {"enabled": enabled, "gameServerProtocolVersion": "0.2.49"}})

    def test_missing_or_malformed_protocol_is_rejected(self):
        for protocol in [None, "0.2", "0.2.49 ", 249, "0.2.x"]:
            with self.subTest(protocol=protocol), self.assertRaises(ValueError):
                self.load({"1.38.4": {"enabled": True, "gameServerProtocolVersion": protocol}})

    def test_disabled_http_deployment_reports_permission_and_rejects_allocation(self):
        with LobbyServer(("127.0.0.1", 0), GameDestination("127.0.0.1", 7000),
                         VersionPolicy(enabled=False)) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = http.client.HTTPConnection(*server.server_address, timeout=5)
                connection.request("GET", "/health")
                response = connection.getresponse()
                health = json.loads(response.read())
                connection.close()
                self.assertEqual(response.status, 200)
                self.assertIs(health["versionEnabled"], False)
                self.assertIsNone(health["acceptedGameServerProtocolVersion"])
                connection = http.client.HTTPConnection(*server.server_address, timeout=5)
                connection.request("POST", "/lobby/allocation", json.dumps(self.request_payload()),
                                   {"Content-Type": "application/json"})
                response = connection.getresponse()
                allocation = json.loads(response.read())
                connection.close()
                self.assertEqual(response.status, 200)
                self.assertIs(allocation["successful"], False)
            finally:
                server.shutdown()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
