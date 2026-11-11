"""Offline unit tests: no network calls."""
import email.message
import pathlib
import sys
import unittest
import urllib.error

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "scripts"))
from public_health import SITES, check, NoRedirect


class FakeResponse:
    def __init__(self, status=200):
        self.status = status
        self.headers = email.message.Message()
        self.headers["Strict-Transport-Security"] = "max-age=31536000"

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class FakeOpener:
    def __init__(self, response=None, exception=None):
        self.response = response
        self.exception = exception
        self.calls = 0

    def open(self, request, timeout):
        self.calls += 1
        assert request.get_method() == "HEAD"
        assert request.full_url.startswith("https://")
        assert timeout == 8
        if self.exception:
            raise self.exception
        return self.response


class PublicHealthTests(unittest.TestCase):
    def test_allowlist_blocks_unapproved_target(self):
        with self.assertRaises(ValueError):
            check("not-owned.example", opener=FakeOpener())

    def test_one_head_and_header_evidence(self):
        opener = FakeOpener(FakeResponse())
        result = check(SITES[0], opener=opener, timer=lambda: 1.0)
        self.assertEqual(opener.calls, 1)
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(result["state"], "OK")
        self.assertEqual(
            result["security_headers"]["strict-transport-security"],
            "max-age=31536000",
        )
        self.assertIsNone(result["security_headers"]["content-security-policy"])

    def test_error_is_not_reported_as_zero(self):
        opener = FakeOpener(exception=urllib.error.URLError("offline"))
        result = check(SITES[0], opener=opener, timer=lambda: 1.0)
        self.assertEqual(result["state"], "UNAVAILABLE")
        self.assertIsNone(result["http_status"])
        self.assertEqual(opener.calls, 1)

    def test_redirects_are_disallowed(self):
        self.assertIsNone(
            NoRedirect().redirect_request(None, None, 302, "Moved", {}, "https://elsewhere.test")
        )


if __name__ == "__main__":
    unittest.main()
