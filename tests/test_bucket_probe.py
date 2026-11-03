import io
import http.client
import socket
import ssl
import unittest
import urllib.error

from tools.check_pkxd_bucket import BASE, PATHS, fetch


class Response(io.BytesIO):
    def __init__(self, body, status=200):
        super().__init__(body)
        self.status, self.headers = status, {"Content-Type": "application/json", "ETag": '"hash"'}

    def geturl(self):
        return BASE + "server-health/health.json"


class BucketProbeTests(unittest.TestCase):
    def test_get_records_json_shape_without_recording_values(self):
        response = fetch(BASE + PATHS[0], "GET", 5, opener=lambda *args, **kwargs: Response(b'{"items":["private-sentinel"]}'))
        self.assertEqual((response["status"], response["jsonValid"], response["jsonKeys"]), (200, True, ["items"]))
        self.assertNotIn("private-sentinel", str(response))

    def test_head_is_independent_from_json_download(self):
        def opener(request, **kwargs):
            self.assertEqual(request.method, "HEAD")
            return Response(b"not JSON")
        response = fetch(BASE + PATHS[0], "HEAD", 5, opener=opener)
        self.assertEqual(response["status"], 200)
        self.assertNotIn("jsonValid", response)

    def test_http_404_keeps_http_status_and_is_not_reported_as_dns_failure(self):
        def opener(*args, **kwargs):
            raise urllib.error.HTTPError(BASE + PATHS[0], 404, "Not Found", {"Content-Type": "text/html"}, io.BytesIO(b"missing"))
        response = fetch(BASE + PATHS[0], "GET", 5, opener=opener)
        self.assertEqual((response["status"], response["jsonValid"]), (404, False))
        self.assertNotIn("error", response)

    def test_network_failures_are_distinguished_without_inventing_http_status(self):
        for reason, category in ((socket.gaierror("unknown host"), "dns"),
                                 (ssl.SSLCertVerificationError("bad certificate"), "tls"),
                                 (TimeoutError(), "timeout"),
                                 (http.client.IncompleteRead(b"partial", 100), "connection")):
            def opener(*args, **kwargs):
                if isinstance(reason, http.client.HTTPException):
                    raise reason
                raise urllib.error.URLError(reason)
            with self.subTest(category=category):
                response = fetch(BASE + PATHS[0], "GET", 5, opener=opener)
                self.assertEqual(response["error"], category)
                self.assertIsNone(response["status"])
