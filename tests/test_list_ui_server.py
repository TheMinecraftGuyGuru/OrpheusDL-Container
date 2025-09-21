import unittest
from http import HTTPStatus
from unittest import mock
from urllib.parse import urlparse

import requests

import list_ui_server


class _TimeoutClient:
    def search(self, *args, **kwargs):
        raise requests.exceptions.Timeout("timeout")


class _DummyHandler(list_ui_server.ListRequestHandler):
    def __init__(self):
        self.responses = []

    def send_json(self, payload, status: HTTPStatus = HTTPStatus.OK) -> None:  # type: ignore[override]
        self.responses.append((payload, status))


class ArtistSearchTimeoutTests(unittest.TestCase):
    def test_handle_artist_search_returns_timeout_error(self):
        handler = _DummyHandler()

        with mock.patch("list_ui_server._get_qobuz_client", return_value=_TimeoutClient()):
            parsed = urlparse("/api/artist-search?q=slow+query")
            handler.handle_artist_search(parsed)

        self.assertEqual(len(handler.responses), 1)
        payload, status = handler.responses[0]
        self.assertEqual(status, HTTPStatus.BAD_GATEWAY)
        self.assertEqual(payload.get("error"), "Qobuz search timed out.")


if __name__ == "__main__":
    unittest.main()
