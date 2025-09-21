import tempfile
import unittest
from http import HTTPStatus
from pathlib import Path
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
        self.client_address = ("127.0.0.1", 0)

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


class RemoveArtistDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        base_path = Path(self._tempdir.name)
        self.music_dir = base_path / "music"
        self.lists_dir = base_path / "lists"
        self.music_dir.mkdir()
        self.lists_dir.mkdir()

        self._original_music_dir = list_ui_server.MUSIC_DIR
        self._original_lists_dir = list_ui_server.LISTS_DIR
        list_ui_server.MUSIC_DIR = self.music_dir
        list_ui_server.LISTS_DIR = self.lists_dir

        self.addCleanup(self._restore_paths)

    def _restore_paths(self) -> None:
        list_ui_server.MUSIC_DIR = self._original_music_dir
        list_ui_server.LISTS_DIR = self._original_lists_dir

    def _write_artists(self, entries):
        with list_ui_server._lock:
            list_ui_server._write_artist_entries_locked(entries)

    def test_remove_artist_deletes_music_directory(self):
        artist_name = "Owl City"
        artist_id = "12345"
        artist_path = self.music_dir / artist_name
        artist_path.mkdir()
        (artist_path / "track.mp3").write_text("data", encoding="utf-8")

        self._write_artists([{"id": artist_id, "name": artist_name}])

        success, message = list_ui_server.remove_entry("artist", 0)

        self.assertTrue(success)
        self.assertIn(artist_name, message)
        self.assertFalse(artist_path.exists())

    def test_remove_artist_without_directory_succeeds(self):
        artist_name = "Imagine Dragons"
        artist_id = "67890"

        self._write_artists([{"id": artist_id, "name": artist_name}])

        success, message = list_ui_server.remove_entry("artist", 0)

        self.assertTrue(success)
        self.assertIn(artist_name, message)
        self.assertFalse((self.music_dir / artist_name).exists())


if __name__ == "__main__":
    unittest.main()
