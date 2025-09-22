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


class DatabaseListStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)

        base_path = Path(self._tempdir.name)
        self.db_path = base_path / "orpheusdl-container.db"

        self._original_lists_db_path = list_ui_server.LISTS_DB_PATH
        self._original_db_initialized = list_ui_server._DB_INITIALIZED

        list_ui_server.LISTS_DB_PATH = self.db_path
        list_ui_server._DB_INITIALIZED = False

        self.addCleanup(self._restore_paths)

    def _restore_paths(self) -> None:
        list_ui_server.LISTS_DB_PATH = self._original_lists_db_path
        list_ui_server._DB_INITIALIZED = self._original_db_initialized

    def test_add_album_stores_id_and_metadata(self) -> None:
        success, message = list_ui_server.add_entry(
            "album",
            "90210",
            display_name="Test Album",
            artist_name="Example Artist",
        )

        self.assertTrue(success, msg=message)

        albums = list_ui_server.read_entries("album")
        self.assertEqual(len(albums), 1)
        album_entry = albums[0]
        self.assertEqual(album_entry.get("id"), "90210")
        self.assertEqual(album_entry.get("title"), "Test Album")
        self.assertEqual(album_entry.get("artist"), "Example Artist")

        duplicate_success, duplicate_message = list_ui_server.add_entry(
            "album",
            "90210",
            display_name="Duplicate Title",
            artist_name="Different Artist",
        )

        self.assertFalse(duplicate_success)
        self.assertIn("already present", duplicate_message)

        removed, remove_message = list_ui_server.remove_entry("album", 0)
        self.assertTrue(removed, msg=remove_message)
        self.assertEqual(list_ui_server.read_entries("album"), [])

    def test_add_track_stores_id_and_metadata(self) -> None:
        success, message = list_ui_server.add_entry(
            "track",
            "808",
            display_name="Test Track",
            artist_name="Example Artist",
            album_title="Example Album",
        )

        self.assertTrue(success, msg=message)

        tracks = list_ui_server.read_entries("track")
        self.assertEqual(len(tracks), 1)
        track_entry = tracks[0]
        self.assertEqual(track_entry.get("id"), "808")
        self.assertEqual(track_entry.get("title"), "Test Track")
        self.assertEqual(track_entry.get("artist"), "Example Artist")
        self.assertEqual(track_entry.get("album"), "Example Album")

        duplicate_success, duplicate_message = list_ui_server.add_entry(
            "track",
            "808",
            display_name="Duplicate Track",
            artist_name="Different Artist",
            album_title="Different Album",
        )

        self.assertFalse(duplicate_success)
        self.assertIn("already present", duplicate_message)

        removed, remove_message = list_ui_server.remove_entry("track", 0)
        self.assertTrue(removed, msg=remove_message)
        self.assertEqual(list_ui_server.read_entries("track"), [])


class RemoveArtistDirectoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        base_path = Path(self._tempdir.name)
        self.music_dir = base_path / "music"
        self.lists_dir = base_path / "lists"
        self.db_path = self.lists_dir / "orpheusdl-container.db"
        self.music_dir.mkdir()
        self.lists_dir.mkdir()

        self._original_music_dir = list_ui_server.MUSIC_DIR
        self._original_lists_db_path = list_ui_server.LISTS_DB_PATH
        self._original_db_initialized = list_ui_server._DB_INITIALIZED
        list_ui_server.MUSIC_DIR = self.music_dir
        list_ui_server.LISTS_DB_PATH = self.db_path
        list_ui_server._DB_INITIALIZED = False

        self.addCleanup(self._restore_paths)

    def _restore_paths(self) -> None:
        list_ui_server.MUSIC_DIR = self._original_music_dir
        list_ui_server.LISTS_DB_PATH = self._original_lists_db_path
        list_ui_server._DB_INITIALIZED = self._original_db_initialized

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
