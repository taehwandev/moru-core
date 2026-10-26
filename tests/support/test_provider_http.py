"""Exercise the real urllib redirect chain without contacting a provider."""
import io
from email.message import Message
from pathlib import Path
import sys
import unittest
import urllib.error
import urllib.parse
import urllib.request
import urllib.response
import uuid
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from support.provider_http import open_provider_request


class ProviderHttpTests(unittest.TestCase):
    def request(self, url="https://openrouter.ai/api/alpha/decisions"):
        return urllib.request.Request(url, data=b"synthetic research only", headers={
            "Authorization": "Bearer synthetic-test-only", "Content-Type": "application/json",
        })

    def test_redirect_does_not_send_a_second_request_or_disclose_credentials(self):
        for code in (301, 302, 303, 307, 308):
            for destination in ("https://other.invalid/collect", "http://openrouter.ai/collect",
                                "https://openrouter.ai/other"):
                with self.subTest(code=code, destination=destination):
                    headers = Message()
                    headers["Location"] = destination
                    response = urllib.response.addinfourl(io.BytesIO(b""), headers,
                                                         self.request().full_url, code)
                    response.msg = "Redirect"
                    with patch.object(urllib.request.HTTPSHandler, "https_open",
                                      return_value=response) as transport:
                        with self.assertRaises(urllib.error.URLError) as error:
                            open_provider_request(self.request(), timeout=3)
                    self.assertEqual(transport.call_count, 1)
                    self.assertNotIn("synthetic-test-only", str(error.exception))

    def test_other_origins_and_embedded_credentials_fail_before_transport(self):
        # Generate throwaway userinfo at runtime; no credential-shaped literal
        # belongs in tracked fixtures, even when it is only illustrative.
        userinfo = f"{uuid.uuid4().hex}:{uuid.uuid4().hex}"
        userinfo_url = urllib.parse.urlunsplit(("https", f"{userinfo}@openrouter.ai", "/", "", ""))
        for url in ("http://openrouter.ai/", "https://other.invalid/", "https://openrouter.ai:8443/",
                    userinfo_url, "https://openrouter.ai/#fragment"):
            with self.subTest(url=url), patch.object(urllib.request.OpenerDirector, "open") as call:
                with self.assertRaises(urllib.error.URLError):
                    open_provider_request(self.request(url), timeout=3)
                call.assert_not_called()

    def test_success_preserves_post_body_auth_and_response(self):
        response = urllib.response.addinfourl(io.BytesIO(b'{"ok":true}'), Message(),
                                             self.request().full_url, 200)
        response.msg = "OK"
        with patch.object(urllib.request.HTTPSHandler, "https_open", return_value=response) as call:
            with open_provider_request(self.request(), timeout=3) as result:
                self.assertEqual(result.read(), b'{"ok":true}')
        sent = call.call_args.args[0]
        self.assertEqual(sent.get_method(), "POST")
        self.assertEqual(sent.data, b"synthetic research only")
        self.assertEqual(sent.get_header("Authorization"), "Bearer synthetic-test-only")


if __name__ == "__main__":
    unittest.main()
