"""Test f1telemetry.update_check module."""
from __future__ import annotations

import io
import json
import unittest
import urllib.error
from unittest import mock

from f1telemetry.src import update_check as uc
from f1telemetry.src.update_check import CheckStatus, check_for_update, is_newer, _version_key


class _FakeResp:
    def __init__(self, data: bytes) -> None:
        self._data = data
    def __enter__(self):
        return io.BytesIO(self._data)
    def __exit__(self, *a):
        return False


def _urlopen_json(obj):
    def _open(req, timeout=None):
        return _FakeResp(json.dumps(obj).encode())
    return _open


def _urlopen_raise(exc):
    def _open(req, timeout=None):
        raise exc
    return _open


class VersionCompareTest(unittest.TestCase):
    def test_key_parsing(self):
        self.assertEqual(_version_key("v0.2.0"), (0, 2, 0, 1))
        self.assertEqual(_version_key("1.2.3+build.5"), (1, 2, 3, 1))
        self.assertEqual(_version_key("0.1.0-beta.1"), (0, 1, 0, 0))  # prerelease ranks lower
        self.assertIsNone(_version_key("not-a-version"))

    def test_is_newer(self):
        self.assertTrue(is_newer("v0.2.0", "0.1.0"))
        self.assertTrue(is_newer("1.0.0", "0.9.9"))
        self.assertFalse(is_newer("0.1.0", "0.1.0"))
        self.assertFalse(is_newer("0.1.0", "0.2.0"))
        self.assertFalse(is_newer("0.1.0-beta.1", "0.1.0"))  # prerelease not newer than release
        self.assertFalse(is_newer("garbage", "0.1.0"))       # unparseable -> not newer


class CheckForUpdateTest(unittest.TestCase):
    def setUp(self):
        # Pretend the build is configured so the network path is exercised.
        self._owner = mock.patch.object(uc, "GITHUB_OWNER", "octocat")
        self._owner.start()
        self.addCleanup(self._owner.stop)

    def test_update_available(self):
        obj = {"tag_name": "v0.2.0", "name": "0.2.0", "body": "Notes",
               "html_url": "https://example/rel", "prerelease": False}
        res = check_for_update("0.1.0", urlopen=_urlopen_json(obj))
        self.assertIs(res.status, CheckStatus.UPDATE_AVAILABLE)
        self.assertEqual(res.release.version, "v0.2.0")
        self.assertEqual(res.release.html_url, "https://example/rel")

    def test_up_to_date_equal(self):
        obj = {"tag_name": "v0.1.0", "name": "0.1.0"}
        res = check_for_update("0.1.0", urlopen=_urlopen_json(obj))
        self.assertIs(res.status, CheckStatus.UP_TO_DATE)

    def test_up_to_date_when_latest_is_older(self):
        obj = {"tag_name": "v0.0.9", "name": "0.0.9"}
        res = check_for_update("0.1.0", urlopen=_urlopen_json(obj))
        self.assertIs(res.status, CheckStatus.UP_TO_DATE)

    def test_http_error_is_graceful(self):
        err = urllib.error.HTTPError("u", 403, "rate limited", {}, None)
        res = check_for_update("0.1.0", urlopen=_urlopen_raise(err))
        self.assertIs(res.status, CheckStatus.ERROR)
        self.assertIn("Could not check", res.message)

    def test_offline_is_graceful(self):
        res = check_for_update("0.1.0", urlopen=_urlopen_raise(urllib.error.URLError("offline")))
        self.assertIs(res.status, CheckStatus.ERROR)

    def test_malformed_json_is_graceful(self):
        def _open(req, timeout=None):
            return _FakeResp(b"{ not json")
        res = check_for_update("0.1.0", urlopen=_open)
        self.assertIs(res.status, CheckStatus.ERROR)

    def test_missing_tag_is_graceful(self):
        res = check_for_update("0.1.0", urlopen=_urlopen_json({"name": "no tag"}))
        self.assertIs(res.status, CheckStatus.ERROR)

    def test_prerelease_list_path(self):
        items = [
            {"tag_name": "v0.3.0-rc.1", "prerelease": True, "draft": False},
            {"tag_name": "v0.2.0", "prerelease": False, "draft": False},
        ]
        with mock.patch.object(uc, "INCLUDE_PRERELEASES", True):
            res = check_for_update("0.1.0", urlopen=_urlopen_json(items))
        self.assertIs(res.status, CheckStatus.UPDATE_AVAILABLE)
        self.assertEqual(res.release.version, "v0.3.0-rc.1")


class ConfigGuardTest(unittest.TestCase):
    def test_unconfigured_owner_returns_error(self):
        with mock.patch.object(uc, "GITHUB_OWNER", "REPLACE_ME"):
            res = check_for_update("0.1.0", urlopen=_urlopen_json({"tag_name": "v9.9.9"}))
        self.assertIs(res.status, CheckStatus.ERROR)
        self.assertIn("aren't configured", res.message)


if __name__ == "__main__":
    unittest.main()