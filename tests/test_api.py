import io
import json
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError

from sius_client.core import Api, ClientError


class ApiTests(unittest.TestCase):
    def test_requests_identify_sius_client(self):
        response = MagicMock()
        response.__enter__.return_value.read.return_value = b'{"success":true,"imported":0}'
        with patch("sius_client.core.build_opener") as opener:
            opener.return_value.open.return_value = response
            api = Api("https://example.test")
            api.token = "test-token"
            api.request("/api/anlaesse/9/shots/import", {"Shots": []})
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.get_header("User-agent"), "SiusClientV2/2.0 (Windows)")
            self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
            self.assertEqual(json.loads(request.data), {"Shots": []})

    def test_403_identifies_access_problem(self):
        error = HTTPError("https://example.test", 403, "Forbidden", {}, io.BytesIO(b"error code: 1010"))
        with patch("sius_client.core.build_opener") as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaisesRegex(ClientError, "Zugriff verweigert.*403"):
                Api("https://example.test").request("/api/login", {})

    def test_401_identifies_login_problem(self):
        error = HTTPError("https://example.test", 401, "Unauthorized", {}, io.BytesIO(b"{}"))
        with patch("sius_client.core.build_opener") as opener:
            opener.return_value.open.side_effect = error
            with self.assertRaisesRegex(ClientError, "Anmeldung"):
                Api("https://example.test").request("/api/login", {})
