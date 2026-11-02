import http.client
import json
import threading
import unittest

from pkxd_server.lobby import GameDestination, LobbyServer


class LobbyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = LobbyServer(("127.0.0.1", 0), GameDestination("127.0.0.1", 7000))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, payload=None, *, method="POST", path="/lobby/allocation", raw=None, content_type="application/json"):
        body = raw if raw is not None else json.dumps(payload).encode("utf-8")
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        try:
            connection.request(method, path, body=body, headers={"Content-Type": content_type})
            response = connection.getresponse()
            data = response.read()
            self.assertEqual(int(response.getheader("Content-Length")), len(data))
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            return response.status, json.loads(data)
        finally:
            connection.close()

    @staticmethod
    def payload(**changes):
        return dict(userToken="test-local-token", gameServerProtocolVersion="0.2.49", isPrivate=False, **changes)

    def test_native_request_reaches_successful_allocation(self):
        with self.assertLogs("pkxd_server.lobby", level="INFO") as logs:
            status, response = self.request(self.payload())
        self.assertEqual(status, 200)
        self.assertIs(response["successful"], True)
        self.assertEqual(response["failureReason"], "")
        self.assertEqual(response["gameServerAddress"], "127.0.0.1")
        self.assertEqual(response["gameServerHosts"], ["127.0.0.1"])
        self.assertEqual(response["gameServerPort"], 7000)
        self.assertEqual(response["gameServerUdpPort"], 0)
        self.assertEqual(response["gameServerType"], "DEFAULT")
        self.assertNotIn("test-local-token", json.dumps(response))
        self.assertNotIn("test-local-token", " ".join(logs.output))

    def test_mismatch_is_a_nonempty_200_response_for_native_error_branch(self):
        for version in ("1.38.4", "0.2.48", "0.2.50", "0.2.49 "):
            with self.subTest(protocol=version):
                payload = self.payload()
                payload["gameServerProtocolVersion"] = version
                status, response = self.request(payload)
                self.assertEqual(status, 200)
                self.assertIs(response["successful"], False)
                self.assertEqual(response["failureReason"], "GAME_SERVER_PROTOCOL_VERSION_MISMATCH")

    def test_health_does_not_claim_gameplay_is_running(self):
        status, response = self.request(method="GET", path="/health")
        self.assertEqual(status, 200)
        self.assertEqual(response["targetAppVersion"], "1.38.4")
        self.assertEqual(response["acceptedGameServerProtocolVersion"], "0.2.49")
        self.assertIs(response["gameTransportImplemented"], False)

    def test_incomplete_and_wrongly_typed_payloads_are_rejected(self):
        payloads = [[], None, {}, {"isPrivate": False},
                    {"userToken": "a", "gameServerProtocolVersion": "0.2.49", "isPrivate": 0},
                    {"userToken": "", "gameServerProtocolVersion": "0.2.49", "isPrivate": False}]
        for payload in payloads:
            with self.subTest(payload=payload):
                status, response = self.request(payload)
                self.assertEqual(status, 400)
                self.assertIs(response["successful"], False)

    def test_other_room_features_are_not_silently_emulated(self):
        for field, value in [("isPrivate", True), ("destinationRoomId", "room"), ("destinationUserId", "user")]:
            payload = self.payload()
            payload[field] = value
            status, response = self.request(payload)
            self.assertEqual(status, 400)
            self.assertEqual(response["failureReason"], "UNSUPPORTED_ALLOCATION")

    def test_invalid_json_and_encoding(self):
        for body in (b'{"userToken":', b"\xff"):
            status, _ = self.request(raw=body)
            self.assertEqual(status, 400)

    def test_body_size_limit(self):
        status, _ = self.request(raw=b" " * (64 * 1024 + 1))
        self.assertEqual(status, 413)

    def test_unknown_paths_do_not_return_fake_success(self):
        for path in ("/version", "/login", "/lobby/allocation/"):
            status, _ = self.request(self.payload(), path=path)
            self.assertEqual(status, 404)

    def test_content_type(self):
        status, _ = self.request(self.payload(), content_type="text/plain")
        self.assertEqual(status, 415)
        status, _ = self.request(self.payload(), content_type="application/json; charset=utf-8")
        self.assertEqual(status, 200)

    def test_tcp_and_optional_udp_configuration(self):
        from pkxd_server.lobby import allocate
        status, response = allocate(self.payload(), GameDestination("192.168.1.10", 7777, 7778))
        self.assertEqual(status, 200)
        self.assertEqual(response["gameServerAddress"], "192.168.1.10")
        self.assertEqual(response["gameServerHosts"], ["192.168.1.10"])
        self.assertEqual(response["gameServerPort"], 7777)
        self.assertEqual(response["gameServerUdpPort"], 7778)

    def test_invalid_game_destinations(self):
        for host, port, udp in [("0.0.0.0", 7000, 0), ("http://localhost", 7000, 0),
                                ("localhost", 0, 0), ("localhost", 7000, -1)]:
            with self.subTest(destination=(host, port, udp)):
                with self.assertRaises(ValueError):
                    GameDestination(host, port, udp)


if __name__ == "__main__":
    unittest.main()
