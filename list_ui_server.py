#!/usr/bin/env python3
"""Simple web UI for managing OrpheusDL list files."""
from __future__ import annotations

import functools
import html
import importlib.util
import json
import logging
import os
import queue
import shutil
import sqlite3
import subprocess
import sys
import threading
import unicodedata
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urlencode, urlparse, quote, unquote

import requests
from notifications import send_discord_notification as _send_discord_notification

LIST_LABELS: Dict[str, str] = {
    "artist": "Artists",
    "album": "Albums",
    "track": "Tracks",
}

AUDIO_FILE_EXTENSIONS = {
    ".flac",
    ".mp3",
    ".aac",
    ".m4a",
    ".m4b",
    ".ogg",
    ".opus",
    ".wav",
    ".aiff",
    ".aif",
    ".alac",
    ".dsf",
    ".dff",
    ".wv",
    ".ape",
    ".wma",
    ".mka",
    ".mp2",
}

ARTIST_SEARCH_SECTION = """
<div class=\"search-block\" data-search-type=\"artist\">
  <h3>Search Qobuz Artists</h3>
  <form id=\"artist-search-form\" class=\"search-form\" autocomplete=\"off\">
    <div class=\"search-grid\">
      <label class=\"input-group\" for=\"artist-search-input\">
        <span class=\"field-label\">Artist</span>
        <input type=\"search\" id=\"artist-search-input\" placeholder=\"Search Qobuz artists\" aria-label=\"Search Qobuz artists\" required>
      </label>
    </div>
    <div class=\"search-actions\">
      <button type=\"submit\" id=\"artist-search-button\" class=\"button primary\">Search</button>
    </div>
  </form>
  <div id=\"artist-search-status\" class=\"search-status\">Use the search to add artists by Qobuz ID.</div>
  <ul id=\"artist-search-results\" class=\"search-results\"></ul>
</div>
""".strip()

ALBUM_SEARCH_SECTION = """
<div class=\"search-block\" data-search-type=\"album\">
  <h3>Search Qobuz Albums</h3>
  <form id=\"album-search-form\" class=\"search-form\" autocomplete=\"off\">
    <div class=\"search-grid\">
      <label class=\"input-group\" for=\"album-search-title\">
        <span class=\"field-label\">Album</span>
        <input type=\"search\" id=\"album-search-title\" placeholder=\"Album name\" aria-label=\"Album name\">
      </label>
      <label class=\"input-group\" for=\"album-search-artist\">
        <span class=\"field-label\">Artist</span>
        <input type=\"search\" id=\"album-search-artist\" placeholder=\"Artist name\" aria-label=\"Album artist\">
      </label>
    </div>
    <div class=\"search-actions\">
      <button type=\"submit\" id=\"album-search-button\" class=\"button primary\">Search</button>
    </div>
  </form>
  <div id=\"album-search-status\" class=\"search-status\">Provide album and artist names for best results.</div>
  <ul id=\"album-search-results\" class=\"search-results\"></ul>
</div>
""".strip()

TRACK_SEARCH_SECTION = """
<div class=\"search-block\" data-search-type=\"track\">
  <h3>Search Qobuz Tracks</h3>
  <form id=\"track-search-form\" class=\"search-form\" autocomplete=\"off\">
    <div class=\"search-grid\">
      <label class=\"input-group\" for=\"track-search-title\">
        <span class=\"field-label\">Track</span>
        <input type=\"search\" id=\"track-search-title\" placeholder=\"Track name\" aria-label=\"Track name\">
      </label>
      <label class=\"input-group\" for=\"track-search-album\">
        <span class=\"field-label\">Album</span>
        <input type=\"search\" id=\"track-search-album\" placeholder=\"Album name\" aria-label=\"Track album\">
      </label>
      <label class=\"input-group\" for=\"track-search-artist\">
        <span class=\"field-label\">Artist</span>
        <input type=\"search\" id=\"track-search-artist\" placeholder=\"Artist name\" aria-label=\"Track artist\">
      </label>
    </div>
    <div class=\"search-actions\">
      <button type=\"submit\" id=\"track-search-button\" class=\"button primary\">Search</button>
    </div>
  </form>
  <div id=\"track-search-status\" class=\"search-status\">Combine track, album, and artist names for precise matches.</div>
  <ul id=\"track-search-results\" class=\"search-results\"></ul>
</div>
""".strip()

SEARCH_SCRIPT = """
<script>
(function() {
  const escapeMap = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': '&quot;', "'": "&#39;"};

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (char) => escapeMap[char] || char);
  }

  function getFieldValues(fields) {
    const values = {};
    fields.forEach((field) => {
      values[field.id] = field.value.trim();
    });
    return values;
  }

  function joinNonEmpty(parts) {
    return parts.map((part) => part.trim()).filter(Boolean).join(' ');
  }

  function attachSearchController(type, config) {
    const form = document.getElementById(config.formId);
    const results = document.getElementById(config.resultsId);
    const status = document.getElementById(config.statusId);
    const fields = (config.fieldIds || []).map((id) => document.getElementById(id)).filter(Boolean);
    if (!form || !results || !status || !fields.length) {
      return;
    }

    let activeController = null;

    function setStatus(message) {
      status.textContent = message;
      status.style.display = message ? 'block' : 'none';
    }

    function render(items) {
      if (!Array.isArray(items) || !items.length) {
        results.innerHTML = '';
        setStatus(config.emptyMessage || 'No results found.');
        return;
      }

      const markup = items.map((item) => config.renderItem(item, escapeHtml)).join('');
      results.innerHTML = markup;
      setStatus(config.successPrompt || 'Select an item to add.');
    }

    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const values = getFieldValues(fields);
      const query = config.buildQuery(values);
      if (!query) {
        setStatus(config.inputHint || 'Enter search details.');
        return;
      }

      if (activeController) {
        activeController.abort();
      }

      const controller = new AbortController();
      activeController = controller;
      setStatus('Searching…');
      results.innerHTML = '';

      try {
        const response = await fetch(config.endpoint + '?q=' + encodeURIComponent(query), {signal: controller.signal});
        if (!response.ok) {
          let detail = 'HTTP ' + response.status;
          try {
            const data = await response.json();
            detail = data.error || data.message || detail;
          } catch (_) {
            const text = await response.text();
            if (text) {
              detail = text;
            }
          }
          throw new Error(detail);
        }

        const payload = await response.json();
        render(payload.results || []);
      } catch (error) {
        if (error.name === 'AbortError') {
          return;
        }
        console.error('[' + type + ' search] Search failed.', error);
        setStatus('Search failed: ' + error.message);
      } finally {
        if (activeController === controller) {
          activeController = null;
        }
      }
    });

    results.addEventListener('click', async (event) => {
      const button = event.target.closest('button[data-select-type]');
      if (!button || button.dataset.selectType !== type) {
        return;
      }

      const payload = config.buildSelectPayload(button.dataset);
      if (!payload) {
        return;
      }

      setStatus('Adding…');
      try {
        const response = await fetch(config.selectEndpoint, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify(payload)
        });
        const data = await response.json();
        if (!response.ok || data.success === false) {
          const message = data.error || data.message || ('HTTP ' + response.status);
          throw new Error(message);
        }
        if (data.redirect) {
          window.location.href = data.redirect;
          return;
        }
        setStatus(data.message || config.addSuccess || 'Item added successfully.');
        results.innerHTML = '';
        fields.forEach((field) => { if (config.clearOnSuccess) { field.value = ''; } });
      } catch (error) {
        console.error('[' + type + ' search] Failed to add entry.', error);
        setStatus('Failed to add entry: ' + error.message);
      }
    });
  }

  const searchConfigs = {
    artist: {
      formId: 'artist-search-form',
      resultsId: 'artist-search-results',
      statusId: 'artist-search-status',
      fieldIds: ['artist-search-input'],
      endpoint: '/api/artist-search',
      selectEndpoint: '/api/artist-select',
      inputHint: 'Enter an artist to search for.',
      emptyMessage: 'No artists found.',
      successPrompt: 'Select an artist to add and download.',
      addSuccess: 'Artist queued for download.',
      buildQuery(values) {
        return values['artist-search-input'];
      },
      buildSelectPayload(dataset) {
        const id = dataset.artistId || dataset.id || '';
        if (!id) {
          return null;
        }
        return {
          id,
          name: dataset.artistName || dataset.name || ''
        };
      },
      renderItem(item, escapeHtml) {
        const rawId = item.id || '';
        const rawName = item.name || '';
        const label = rawName || rawId;
        const safeId = escapeHtml(rawId);
        const safeLabel = escapeHtml(label);
        const datasetName = escapeHtml(rawName || rawId);
        const photo = typeof item.photo === 'string' ? item.photo.trim() : '';
        const image = typeof item.image === 'string' ? item.image.trim() : '';
        const imageSource = photo || image;
        const safeImage = imageSource ? escapeHtml(imageSource) : '';
        const altText = label ? label + ' photo' : 'Artist photo';
        const safeAlt = escapeHtml(altText);
        const imageHtml = safeImage
          ? '<div class="search-thumb"><img src="' + safeImage + '" alt="' + safeAlt + '" loading="lazy"></div>'
          : '';
        const secondary = safeId ? '<div class="search-secondary">ID: ' + safeId + '</div>' : '';
        return (
          '<li class="search-result">' +
          imageHtml +
          '<div class="search-meta">' +
          '<div class="search-primary">' + safeLabel + '</div>' +
          secondary +
          '</div>' +
          '<button type="button" class="button success" data-select-type="artist" data-artist-id="' + safeId +
          '" data-artist-name="' + datasetName + '">Add</button>' +
          '</li>'
        );
      }
    },
    album: {
      formId: 'album-search-form',
      resultsId: 'album-search-results',
      statusId: 'album-search-status',
      fieldIds: ['album-search-title', 'album-search-artist'],
      endpoint: '/api/album-search',
      selectEndpoint: '/api/album-select',
      inputHint: 'Enter at least an album or artist name.',
      emptyMessage: 'No albums found.',
      successPrompt: 'Select an album to queue for download.',
      addSuccess: 'Album queued for download.',
      clearOnSuccess: true,
      buildQuery(values) {
        return joinNonEmpty([values['album-search-title'] || '', values['album-search-artist'] || '']);
      },
      buildSelectPayload(dataset) {
        const id = dataset.id || '';
        if (!id) {
          return null;
        }
        return {
          id,
          title: dataset.title || '',
          artist: dataset.artist || '',
          value: dataset.value || '',
          lookup: dataset.lookup || '',
          image: dataset.image || '',
          photo: dataset.photo || ''
        };
      },
      renderItem(item, escapeHtml) {
        const title = escapeHtml(item.title || '');
        const artist = escapeHtml(item.artist || '');
        const year = escapeHtml(item.year || '');
        const lookup = escapeHtml(item.lookup || '');
        const value = escapeHtml(item.value || '');
        const id = escapeHtml(item.id || '');
        const cached = typeof item.photo === 'string' ? item.photo.trim() : '';
        const remote = typeof item.image === 'string' ? item.image.trim() : '';
        const imageSource = cached || remote;
        const safeImage = imageSource ? escapeHtml(imageSource) : '';
        const safeRemote = remote ? escapeHtml(remote) : '';
        const safeCached = cached ? escapeHtml(cached) : '';
        const altBase = item.title || item.value || 'Album';
        const altText = escapeHtml(String(altBase) + ' cover');
        const imageHtml = safeImage
          ? '<div class="search-thumb"><img src="' + safeImage + '" alt="' + altText + '" loading="lazy"></div>'
          : '';
        const secondary =
          '<div class="search-secondary">' +
          (artist ? 'Artist: ' + artist : 'Artist unknown') +
          (year ? ' · ' + year : '') +
          '</div>';
        const primary = title || value || escapeHtml('Unknown album');
        return (
          '<li class="search-result">' +
          imageHtml +
          '<div class="search-meta">' +
          '<div class="search-primary">' + primary + '</div>' +
          secondary +
          '</div>' +
          '<button type="button" class="button success" data-select-type="album" data-id="' + id + '" data-title="' + title + '" data-artist="' + artist + '" data-value="' + value + '" data-lookup="' + lookup + '" data-image="' + safeRemote + '" data-photo="' + safeCached + '">Add</button>' +
          '</li>'
        );
      }
    },
    track: {
      formId: 'track-search-form',
      resultsId: 'track-search-results',
      statusId: 'track-search-status',
      fieldIds: ['track-search-title', 'track-search-album', 'track-search-artist'],
      endpoint: '/api/track-search',
      selectEndpoint: '/api/track-select',
      inputHint: 'Enter at least a track name.',
      emptyMessage: 'No tracks found.',
      successPrompt: 'Select a track to queue for download.',
      addSuccess: 'Track queued for download.',
      clearOnSuccess: true,
      buildQuery(values) {
        return joinNonEmpty([
          values['track-search-title'] || '',
          values['track-search-album'] || '',
          values['track-search-artist'] || ''
        ]);
      },
      buildSelectPayload(dataset) {
        const id = dataset.id || '';
        if (!id) {
          return null;
        }
        return {
          id,
          title: dataset.title || '',
          album: dataset.album || '',
          artist: dataset.artist || '',
          value: dataset.value || '',
          lookup: dataset.lookup || '',
          album_id: dataset.albumId || '',
          image: dataset.image || '',
          photo: dataset.photo || ''
        };
      },
      renderItem(item, escapeHtml) {
        const title = escapeHtml(item.title || '');
        const album = escapeHtml(item.album || '');
        const artist = escapeHtml(item.artist || '');
        const value = escapeHtml(item.value || '');
        const lookup = escapeHtml(item.lookup || '');
        const id = escapeHtml(item.id || '');
        const cached = typeof item.photo === 'string' ? item.photo.trim() : '';
        const remote = typeof item.image === 'string' ? item.image.trim() : '';
        const imageSource = cached || remote;
        const safeImage = imageSource ? escapeHtml(imageSource) : '';
        const safeRemote = remote ? escapeHtml(remote) : '';
        const safeCached = cached ? escapeHtml(cached) : '';
        const albumId = escapeHtml(item.album_id || '');
        const altBase = item.title || item.value || 'Track';
        const altText = escapeHtml(String(altBase) + ' cover');
        const imageHtml = safeImage
          ? '<div class="search-thumb"><img src="' + safeImage + '" alt="' + altText + '" loading="lazy"></div>'
          : '';
        const secondary =
          '<div class="search-secondary">' +
          (artist ? 'Artist: ' + artist : 'Artist unknown') +
          (album ? ' · Album: ' + album : '') +
          '</div>';
        const primary = title || value || escapeHtml('Unknown track');
        return (
          '<li class="search-result">' +
          imageHtml +
          '<div class="search-meta">' +
          '<div class="search-primary">' + primary + '</div>' +
          secondary +
          '</div>' +
          '<button type="button" class="button success" data-select-type="track" data-id="' + id + '" data-title="' + title + '" data-album="' + album + '" data-artist="' + artist + '" data-value="' + value + '" data-lookup="' + lookup + '" data-album-id="' + albumId + '" data-image="' + safeRemote + '" data-photo="' + safeCached + '">Add</button>' +
          '</li>'
        );
      }
    }
  };

  Object.entries(searchConfigs).forEach(([type, config]) => {
    attachSearchController(type, config);
  });

  const selector = document.getElementById('list-selector');
  const sections = document.querySelectorAll('.list-section');
  function showSection(target) {
    sections.forEach((section) => {
      section.classList.toggle('active', section.dataset.list === target);
    });
    if (selector && selector.value !== target) {
      selector.value = target;
    }
  }

  if (selector && sections.length) {
    selector.addEventListener('change', () => {
      showSection(selector.value);
    });
    const active = Array.from(sections).find((section) => section.classList.contains('active'));
    showSection(active ? active.dataset.list : selector.value || sections[0].dataset.list);
  }
})();
</script>
""".strip()


def _publish_discord_event(
    event: str,
    message: str,
    *,
    level: str = "info",
    title: str | None = "OrpheusDL Container",
    details: Dict[str, str] | None = None,
) -> None:
    """Safely send a Discord notification for the provided event."""

    try:
        _send_discord_notification(
            message,
            event=event,
            level=level,
            title=title,
            details=details,
        )
    except Exception:  # pragma: no cover - defensive guard
        logging.getLogger(__name__).debug(
            "Failed to publish Discord notification for event %s.",
            event,
            exc_info=True,
        )

def _resolve_lists_db_path() -> Path:
    explicit_paths = (
        os.environ.get("LISTS_DB_PATH"),
        os.environ.get("LISTS_DB"),
    )
    for value in explicit_paths:
        if value:
            return Path(value).expanduser()
    legacy_dir = os.environ.get("LISTS_DIR")
    if legacy_dir:
        return Path(legacy_dir).expanduser() / "orpheusdl-container.db"
    return Path("/data/orpheusdl-container.db")


LISTS_DB_PATH = _resolve_lists_db_path()
MUSIC_DIR = Path(os.environ.get("MUSIC_DIR", "/data/music"))
PHOTOS_DIR = Path(os.environ.get("LISTS_PHOTO_DIR", "/data/photos"))
WEB_HOST = os.environ.get("LISTS_WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("LISTS_WEB_PORT", "8080"))

BASE_DIR = Path(__file__).resolve().parent
_ORPHEUSDL_PATH = BASE_DIR / "external" / "orpheusdl"
if _ORPHEUSDL_PATH.exists():
    path_str = str(_ORPHEUSDL_PATH)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

_QOBUZ_MODULE_LOCK = threading.RLock()
_QOBUZ_API_MODULE = None
_QOBUZ_CLIENT = None
_QOBUZ_CLIENT_CREDS: Optional[Dict[str, str]] = None

_QOBUZ_ENV_MAPPING: Dict[str, Tuple[str, ...]] = {
    "app_id": ("QOBUZ_APP_ID", "APP_ID", "app_id"),
    "app_secret": ("QOBUZ_APP_SECRET", "APP_SECRET", "app_secret"),
    "user_id": ("QOBUZ_USER_ID", "USER_ID", "user_id"),
    "token": (
        "QOBUZ_TOKEN",
        "QOBUZ_USER_AUTH_TOKEN",
        "QOBUZ_AUTH_TOKEN",
        "TOKEN",
        "USER_AUTH_TOKEN",
        "user_auth_token",
        "token",
    ),
}

_lock = threading.RLock()
_async_lock = threading.Lock()
_async_messages: List[Tuple[str, bool]] = []
_photo_lock = threading.RLock()

_orpheus_worker: Optional[threading.Thread] = None
_orpheus_worker_lock = threading.Lock()
_orpheus_queue: "queue.Queue[Tuple[str, Callable[[], None]]]" = queue.Queue()

_DB_INITIALIZED = False


def _database_path() -> Path:
    return LISTS_DB_PATH


def _get_database_connection() -> sqlite3.Connection:
    LISTS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_database_path(), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS artists (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_checked_at TEXT
        );

        CREATE TABLE IF NOT EXISTS albums (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            artist TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_checked_at TEXT
        );

        CREATE TABLE IF NOT EXISTS tracks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            artist TEXT NOT NULL DEFAULT '',
            album TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_checked_at TEXT
        );
        """
    )

    for table_name in ("artists", "albums", "tracks"):
        columns = {
            (row["name"] if isinstance(row, sqlite3.Row) else row[1])
            for row in conn.execute(f"PRAGMA table_info({table_name})")
        }
        if "last_checked_at" not in columns:
            conn.execute(
                f"ALTER TABLE {table_name} ADD COLUMN last_checked_at TEXT"
            )


def _ensure_database_ready_locked() -> None:
    global _DB_INITIALIZED
    LISTS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if _DB_INITIALIZED and _database_path().exists():
        return
    conn = _get_database_connection()
    try:
        _create_tables(conn)
        conn.commit()
    finally:
        conn.close()
        _DB_INITIALIZED = True


def _read_artist_entries_locked() -> List[Dict[str, str]]:
    _ensure_database_ready_locked()
    conn = _get_database_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, last_checked_at FROM artists ORDER BY created_at, rowid"
        ).fetchall()
    finally:
        conn.close()

    entries: List[Dict[str, str]] = []
    for row in rows:
        artist_id = (row["id"] if isinstance(row, sqlite3.Row) else row[0]) or ""
        artist_name = (row["name"] if isinstance(row, sqlite3.Row) else row[1]) or ""
        last_checked = (
            row["last_checked_at"] if isinstance(row, sqlite3.Row) else row[2]
        )
        artist_id = str(artist_id).strip()
        if not artist_id:
            continue
        entries.append(
            {
                "id": artist_id,
                "name": str(artist_name).strip(),
                "last_checked_at": str(last_checked or "").strip(),
            }
        )
    return entries


def _write_artist_entries_locked(entries: List[Dict[str, str]]) -> None:
    _ensure_database_ready_locked()
    conn = _get_database_connection()
    try:
        existing_rows = conn.execute(
            "SELECT id, last_checked_at FROM artists"
        ).fetchall()
        preserved: Dict[str, str | None] = {}
        for row in existing_rows:
            raw_id = (row["id"] if isinstance(row, sqlite3.Row) else row[0]) or ""
            key = str(raw_id).strip()
            if not key:
                continue
            value = row["last_checked_at"] if isinstance(row, sqlite3.Row) else row[1]
            preserved[key] = value

        conn.execute("DELETE FROM artists")
        for entry in entries:
            artist_id = str(entry.get("id", "")).strip()
            if not artist_id:
                continue
            artist_name = str(entry.get("name", "")).strip()
            last_checked = preserved.get(artist_id)
            conn.execute(
                "INSERT INTO artists (id, name, last_checked_at) VALUES (?, ?, ?)",
                (artist_id, artist_name, last_checked),
            )
        conn.commit()
    finally:
        conn.close()


def _delete_artist_directory(artist_name: str) -> None:
    artist_name = artist_name.strip()
    if not artist_name:
        return

    base_dir = MUSIC_DIR
    try:
        base_resolved = base_dir.resolve(strict=False)
        target = (base_dir / artist_name).resolve(strict=False)
    except Exception as exc:  # pragma: no cover - unexpected resolution failure
        logging.warning(
            "Failed to resolve music directory for artist %r: %s.",
            artist_name,
            exc,
        )
        return

    try:
        target.relative_to(base_resolved)
    except ValueError:
        logging.warning(
            "Refusing to delete artist directory outside music base: %s.",
            target,
        )
        return

    if target == base_resolved:
        logging.warning(
            "Refusing to delete music base directory for artist %r.",
            artist_name,
        )
        return

    try:
        path_obj = base_dir / artist_name
        if path_obj.is_dir():
            shutil.rmtree(path_obj)
            logging.info(
                "Deleted music directory for artist %r at %s.",
                artist_name,
                path_obj,
            )
        elif path_obj.exists():
            path_obj.unlink()
            logging.info(
                "Deleted music file for artist %r at %s.",
                artist_name,
                path_obj,
            )
        else:
            logging.debug(
                "Music directory for artist %r not found at %s.",
                artist_name,
                path_obj,
            )
    except FileNotFoundError:
        logging.debug(
            "Music directory already missing for artist %r at %s.",
            artist_name,
            base_dir / artist_name,
        )
    except Exception as exc:  # pragma: no cover - filesystem failure
        logging.warning(
            "Failed to delete music directory for artist %r at %s: %s.",
            artist_name,
            base_dir / artist_name,
            exc,
        )


def _normalize_photo_identifier(identifier: str) -> Optional[str]:
    if not identifier:
        return None
    normalized = str(identifier).strip()
    if not normalized:
        return None
    if normalized.startswith(".") or "/" in normalized or "\\" in normalized or ".." in normalized:
        return None
    return normalized


def _normalize_name_for_match(value: str) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    normalized = "".join(
        ch for ch in normalized if not unicodedata.combining(ch)
    )
    lowered = normalized.casefold()
    return "".join(ch for ch in lowered if ch.isalnum())


def _name_matches(candidate: str, pattern: str) -> bool:
    candidate_norm = _normalize_name_for_match(candidate)
    pattern_norm = _normalize_name_for_match(pattern)
    if not candidate_norm or not pattern_norm:
        return False
    return pattern_norm in candidate_norm


def _is_within_music_dir(path: Path) -> bool:
    try:
        base = MUSIC_DIR.resolve(strict=False)
        target = path.resolve(strict=False)
    except Exception:
        return False

    try:
        target.relative_to(base)
    except ValueError:
        return False
    return True


def _candidate_artist_directories(artist_name: str) -> List[Path]:
    directories: List[Path] = []
    try:
        if not MUSIC_DIR.exists():
            return []
        for child in MUSIC_DIR.iterdir():
            if not child.is_dir():
                continue
            if not artist_name:
                directories.append(child)
            elif _name_matches(child.name, artist_name):
                directories.append(child)
        direct = MUSIC_DIR / artist_name
        if direct.is_dir() and direct not in directories:
            directories.append(direct)
    except OSError as exc:
        logging.debug("Failed to enumerate artist directories: %s", exc)
    return directories


def _find_album_directories(artist_name: str, album_title: str) -> List[Path]:
    matches: List[Path] = []
    if not album_title:
        return matches

    seen: set[str] = set()

    def add_candidate(path: Path) -> None:
        try:
            resolved = str(path.resolve(strict=False))
        except Exception:
            resolved = str(path)
        if resolved in seen:
            return
        seen.add(resolved)
        matches.append(path)

    candidates = _candidate_artist_directories(artist_name)
    if not candidates:
        candidates = [MUSIC_DIR]

    for directory in candidates:
        if not directory.exists() or not directory.is_dir():
            continue
        try:
            for child in directory.iterdir():
                if not child.is_dir():
                    continue
                if _name_matches(child.name, album_title):
                    add_candidate(child)
        except OSError as exc:
            logging.debug(
                "Failed to inspect contents of %s while searching for album %r: %s.",
                directory,
                album_title,
                exc,
            )

    return matches


def _find_track_files(album_directory: Path, track_title: str) -> List[Path]:
    matches: List[Path] = []
    if not track_title or not album_directory.exists():
        return matches

    normalized_track = _normalize_name_for_match(track_title)
    if not normalized_track:
        return matches

    try:
        for path in album_directory.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix.lower() not in AUDIO_FILE_EXTENSIONS:
                continue
            stem_norm = _normalize_name_for_match(path.stem)
            if not stem_norm:
                continue
            if normalized_track in stem_norm:
                matches.append(path)
    except OSError as exc:
        logging.debug(
            "Failed to search for track %r inside %s: %s.",
            track_title,
            album_directory,
            exc,
        )

    return matches


def _album_has_audio_files(album_directory: Path) -> bool:
    try:
        for path in album_directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in AUDIO_FILE_EXTENSIONS:
                return True
    except OSError as exc:
        logging.debug(
            "Failed to inspect album directory %s for remaining audio files: %s.",
            album_directory,
            exc,
        )
    return False


def _remove_album_media(
    artist_name: str, album_title: str
) -> Tuple[bool, List[Tuple[str, bool]]]:
    messages: List[Tuple[str, bool]] = []
    album_dirs = _find_album_directories(artist_name, album_title)
    if not album_dirs:
        return True, messages

    if len(album_dirs) > 1:
        message = (
            f"Multiple album folders matched '{album_title}'. "
            "Remove the correct folder manually."
        )
        logging.warning(
            "Skipping automatic deletion for album %r because multiple directories were found: %s.",
            album_title,
            album_dirs,
        )
        messages.append((message, True))
        return False, messages

    album_dir = album_dirs[0]
    if not _is_within_music_dir(album_dir):
        logging.warning(
            "Refusing to delete album directory outside of music base: %s.",
            album_dir,
        )
        messages.append(
            (
                f"Refused to delete album folder at {album_dir} because it is outside the music directory.",
                True,
            )
        )
        return False, messages

    try:
        shutil.rmtree(album_dir)
        logging.info(
            "Deleted album directory for %r at %s.",
            album_title,
            album_dir,
        )
    except FileNotFoundError:
        logging.debug(
            "Album directory already missing for %r at %s.",
            album_title,
            album_dir,
        )
    except Exception as exc:  # pragma: no cover - filesystem failure
        logging.warning(
            "Failed to delete album directory for %r at %s: %s.",
            album_title,
            album_dir,
            exc,
        )
        messages.append(
            (
                f"Failed to delete album folder for '{album_title}': {exc}",
                True,
            )
        )
        return False, messages

    return True, messages


def _remove_track_media(
    artist_name: str, album_title: str, track_title: str
) -> Tuple[bool, List[Tuple[str, bool]]]:
    messages: List[Tuple[str, bool]] = []
    album_dirs = _find_album_directories(artist_name, album_title)
    if not album_dirs:
        return True, messages

    if len(album_dirs) > 1:
        message = (
            f"Multiple album folders matched '{album_title}'. Track removal was skipped."
        )
        logging.warning(
            "Skipping track deletion for %r because multiple album directories were found: %s.",
            track_title,
            album_dirs,
        )
        messages.append((message, True))
        return False, messages

    album_dir = album_dirs[0]
    if not _is_within_music_dir(album_dir):
        logging.warning(
            "Refusing to delete track because album directory is outside music base: %s.",
            album_dir,
        )
        messages.append(
            (
                f"Refused to delete tracks from {album_dir} because it is outside the music directory.",
                True,
            )
        )
        return False, messages

    track_files = _find_track_files(album_dir, track_title)
    if not track_files:
        logging.debug(
            "Track %r not found under album directory %s.",
            track_title,
            album_dir,
        )
        return True, messages

    if len(track_files) > 1:
        message = (
            f"Multiple files matched track '{track_title}'. Track removal was skipped."
        )
        logging.warning(
            "Skipping deletion for track %r because multiple files were found: %s.",
            track_title,
            track_files,
        )
        messages.append((message, True))
        return False, messages

    track_path = track_files[0]
    try:
        track_path.unlink()
        logging.info("Deleted track file %s for %r.", track_path, track_title)
    except FileNotFoundError:
        logging.debug(
            "Track file already missing for %r at %s.",
            track_title,
            track_path,
        )
    except Exception as exc:  # pragma: no cover - filesystem failure
        logging.warning(
            "Failed to delete track file %s for %r: %s.",
            track_path,
            track_title,
            exc,
        )
        messages.append(
            (
                f"Failed to delete track file for '{track_title}': {exc}",
                True,
            )
        )
        return False, messages

    if not _album_has_audio_files(album_dir):
        try:
            shutil.rmtree(album_dir)
            logging.info(
                "Removed empty album directory %s after deleting track %r.",
                album_dir,
                track_title,
            )
        except FileNotFoundError:
            logging.debug(
                "Album directory %s already missing after deleting track %r.",
                album_dir,
                track_title,
            )
        except Exception as exc:
            logging.warning(
                "Failed to remove empty album directory %s after deleting track %r: %s.",
                album_dir,
                track_title,
                exc,
            )
            messages.append(
                (
                    f"Track '{track_title}' was removed but the album folder could not be deleted: {exc}",
                    True,
                )
            )

    return True, messages


def _photo_file_path(identifier: str) -> Path:
    return PHOTOS_DIR / identifier


def _cached_photo_url(identifier: str) -> str:
    normalized = _normalize_photo_identifier(identifier)
    if not normalized:
        return ""

    path = _photo_file_path(normalized)
    with _photo_lock:
        if path.exists() and path.is_file() and path.stat().st_size > 0:
            return f"/photos/{quote(normalized, safe='')}"
    return ""


def _ensure_cached_photo(identifier: str, image_url: str | None) -> str:
    normalized = _normalize_photo_identifier(identifier)
    if not normalized:
        return ""

    existing = _cached_photo_url(normalized)
    if existing:
        return existing

    if not image_url:
        return ""

    try:
        response = requests.get(str(image_url), timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        logging.warning(
            "Failed to download photo for %s from %s: %s.",
            normalized,
            image_url,
            exc,
        )
        return ""

    data = response.content
    if not data:
        logging.debug("Photo response for %s was empty.", normalized)
        return ""

    path = _photo_file_path(normalized)
    with _photo_lock:
        if path.exists() and path.is_file() and path.stat().st_size > 0:
            return f"/photos/{quote(normalized, safe='')}"

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logging.warning(
                "Failed to create photo directory %s: %s.",
                path.parent,
                exc,
            )
            return ""

        temp_path = path.with_suffix(".tmp")
        try:
            with temp_path.open("wb") as handle:
                handle.write(data)
            temp_path.replace(path)
        except OSError as exc:
            logging.warning(
                "Failed to store photo for %s: %s.",
                normalized,
                exc,
            )
            try:
                temp_path.unlink()
            except OSError:
                pass
            return ""

    logging.debug("Cached photo for %s at %s.", normalized, path)
    return f"/photos/{quote(normalized, safe='')}"


def _artist_photo_key(artist_id: str) -> Optional[str]:
    return _normalize_photo_identifier(artist_id)


def _album_photo_key(album_id: str) -> Optional[str]:
    normalized = _normalize_photo_identifier(album_id)
    if not normalized:
        return None
    return _normalize_photo_identifier(f"album_{normalized}")


def _cached_artist_photo_url(artist_id: str) -> str:
    key = _artist_photo_key(artist_id)
    if not key:
        return ""
    return _cached_photo_url(key)


def _cached_album_photo_url(album_id: str) -> str:
    key = _album_photo_key(album_id)
    if not key:
        return ""
    return _cached_photo_url(key)


def _ensure_artist_photo(artist_id: str, image_url: str | None) -> str:
    key = _artist_photo_key(artist_id)
    if not key:
        return ""
    return _ensure_cached_photo(key, image_url)


def _ensure_album_photo(album_id: str, image_url: str | None) -> str:
    key = _album_photo_key(album_id)
    if not key:
        return ""
    return _ensure_cached_photo(key, image_url)


def purge_cached_photos() -> int:
    with _photo_lock:
        if not PHOTOS_DIR.exists():
            return 0

        removed = 0
        for child in PHOTOS_DIR.iterdir():
            if not child.is_file():
                continue
            try:
                child.unlink()
                removed += 1
            except OSError as exc:
                logging.warning(
                    "Failed to remove cached photo %s: %s.",
                    child,
                    exc,
                )
        return removed


def download_missing_photos() -> Tuple[int, int, List[Tuple[str, bool]]]:
    ensure_lists_exist()

    try:
        session = _get_qobuz_client()
    except RuntimeError:
        raise

    messages: List[Tuple[str, bool]] = []
    downloaded_artists = 0
    downloaded_albums = 0
    processed_albums: Set[str] = set()

    artists = read_entries("artist")
    for entry in artists:
        artist_id = (entry.get("id") or "").strip()
        if not artist_id or _cached_artist_photo_url(artist_id):
            continue
        artist_label = (entry.get("name") or "").strip() or artist_id

        try:
            data = session.get_artist(artist_id)
        except Exception as exc:  # pragma: no cover - network failure
            logging.warning(
                "Failed to load artist details for %s: %s.",
                artist_id,
                exc,
            )
            messages.append((f"Failed to fetch artist '{artist_label}': {exc}", True))
            continue

        image_url = _pick_first_url(
            data.get("image"),
            data.get("images"),
            data.get("picture"),
            data.get("artist_picture"),
            data.get("artist_picture_url"),
        )

        cached = _ensure_artist_photo(artist_id, image_url)
        if cached:
            downloaded_artists += 1
        else:
            messages.append(
                (f"No image available for artist '{artist_label}'.", False)
            )

    albums = read_entries("album")
    for entry in albums:
        album_id = (entry.get("id") or "").strip()
        if not album_id:
            continue
        processed_albums.add(album_id)
        if _cached_album_photo_url(album_id):
            continue
        album_title = (entry.get("title") or "").strip() or album_id

        try:
            data = session.get_album(album_id)
        except Exception as exc:  # pragma: no cover - network failure
            logging.warning(
                "Failed to load album details for %s: %s.",
                album_id,
                exc,
            )
            messages.append((f"Failed to fetch album '{album_title}': {exc}", True))
            continue

        image_url = _pick_first_url(
            data.get("image"),
            data.get("images"),
            data.get("cover"),
            data.get("picture"),
            (data.get("album") or {}).get("image"),
            (data.get("album") or {}).get("cover"),
        )

        cached = _ensure_album_photo(album_id, image_url)
        if cached:
            downloaded_albums += 1
        else:
            messages.append(
                (f"No cover available for album '{album_title}'.", False)
            )

    tracks = read_entries("track")
    for entry in tracks:
        track_id = (entry.get("id") or "").strip()
        if not track_id:
            continue

        try:
            data = session.get_track(track_id)
        except Exception as exc:  # pragma: no cover - network failure
            logging.warning(
                "Failed to load track details for %s: %s.",
                track_id,
                exc,
            )
            track_label = (entry.get("title") or "").strip() or track_id
            messages.append((f"Failed to fetch track '{track_label}': {exc}", True))
            continue

        album_info = data.get("album")
        if not isinstance(album_info, dict):
            continue

        raw_album_id = album_info.get("id")
        if not raw_album_id:
            continue

        album_id = str(raw_album_id)
        if album_id in processed_albums:
            continue
        processed_albums.add(album_id)

        album_title = _pick_first_str(album_info.get("title"), album_info.get("name")) or album_id
        if _cached_album_photo_url(album_id):
            continue

        image_url = _pick_first_url(
            album_info.get("image"),
            album_info.get("images"),
            album_info.get("cover"),
            album_info.get("picture"),
            data.get("image"),
            data.get("cover"),
        )

        cached = _ensure_album_photo(album_id, image_url)
        if cached:
            downloaded_albums += 1
        else:
            messages.append(
                (
                    f"No cover available for album '{album_title}' linked to track '{entry.get('title') or track_id}'.",
                    False,
                )
            )

    return downloaded_artists, downloaded_albums, messages
def _pick_first_url(*candidates: Any) -> str:
    for candidate in candidates:
        if isinstance(candidate, str):
            text = candidate.strip()
            if text:
                return text
        elif isinstance(candidate, dict):
            keys = (
                "large",
                "extralarge",
                "extra_large",
                "hires",
                "medium",
                "small",
                "url",
                "href",
                "picture",
                "cover",
            )
            for key in keys:
                if key in candidate:
                    url = _pick_first_url(candidate.get(key))
                    if url:
                        return url
        elif isinstance(candidate, list):
            for item in candidate:
                url = _pick_first_url(item)
                if url:
                    return url
    return ""


def _detect_photo_mime(data: bytes) -> str:
    if len(data) >= 3 and data.startswith(b"\xFF\xD8\xFF"):
        return "image/jpeg"
    if len(data) >= 8 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(data) >= 6 and data[:6] in {b"GIF87a", b"GIF89a"}:
        return "image/gif"
    if len(data) >= 2 and data.startswith(b"BM"):
        return "image/bmp"
    if len(data) >= 4 and data[:4] in {b"II*\x00", b"MM\x00*"}:
        return "image/tiff"
    if (
        len(data) >= 12
        and data.startswith(b"RIFF")
        and data[8:12] == b"WEBP"
    ):
        return "image/webp"
    return "application/octet-stream"


def _load_qobuz_api_module():
    global _QOBUZ_API_MODULE
    with _QOBUZ_MODULE_LOCK:
        if _QOBUZ_API_MODULE is not None:
            return _QOBUZ_API_MODULE

        module_paths = [
            BASE_DIR / "external" / "orpheusdl-qobuz" / "qobuz_api.py",
            Path("/orpheusdl/modules/qobuz/qobuz_api.py"),
        ]

        for module_path in module_paths:
            if not module_path.exists():
                continue

            logging.debug("Loading Qobuz API module from %s", module_path)
            spec = importlib.util.spec_from_file_location(
                "orpheusdl_qobuz_api", module_path
            )
            if spec is None or spec.loader is None:
                continue

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _QOBUZ_API_MODULE = module
            logging.info("Qobuz API module loaded successfully from %s.", module_path)
            return module

        raise RuntimeError("Qobuz integration is unavailable.")


def _get_env_value(names: Tuple[str, ...]) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def _collect_qobuz_credentials() -> Dict[str, str]:
    creds = {
        key: _get_env_value(names) for key, names in _QOBUZ_ENV_MAPPING.items()
    }
    logging.info(
        "Collected Qobuz credential hints: app_id=%s app_secret=%s user_id=%s token=%s",
        "set" if creds.get("app_id") else "missing",
        "set" if creds.get("app_secret") else "missing",
        "set" if creds.get("user_id") else "missing",
        "set" if creds.get("token") else "missing",
    )
    if not creds.get("app_id"):
        raise RuntimeError("Qobuz app_id is not configured.")
    return creds


def _get_qobuz_client():
    global _QOBUZ_CLIENT, _QOBUZ_CLIENT_CREDS
    creds = _collect_qobuz_credentials()

    with _QOBUZ_MODULE_LOCK:
        if _QOBUZ_CLIENT is not None and _QOBUZ_CLIENT_CREDS == creds:
            logging.debug("Reusing cached Qobuz client instance.")
            return _QOBUZ_CLIENT

        module = _load_qobuz_api_module()
        session = module.Qobuz(
            creds["app_id"],
            creds.get("app_secret", ""),
            RuntimeError,
        )
        request_parent = getattr(session, "s", None) or getattr(session, "session", None)
        if request_parent is not None and hasattr(request_parent, "request"):
            original_request = request_parent.request

            @functools.wraps(original_request)
            def request_with_timeout(method, url, *args, **kwargs):
                if kwargs.get("timeout") is None:
                    kwargs["timeout"] = 10
                return original_request(method, url, *args, **kwargs)

            request_parent.request = request_with_timeout
        token = creds.get("token")
        if token:
            session.auth_token = token
        user_id = creds.get("user_id")
        if user_id:
            setattr(session, "user_id", user_id)

        _QOBUZ_CLIENT = session
        _QOBUZ_CLIENT_CREDS = creds
        logging.info("Created new Qobuz client session with provided credentials.")
        return session


def _qobuz_search(kind: str, query: str, limit: int = 10) -> Dict[str, Any]:
    if limit <= 0:
        limit = 10

    logging.info(
        "Starting Qobuz %s search for query %r with limit %s.",
        kind,
        query,
        limit,
    )
    session = _get_qobuz_client()

    try:
        return session.search(kind, query, limit=limit)
    except RuntimeError as exc:
        message = str(exc)
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            raise RuntimeError(message) from exc
        else:
            if isinstance(payload, dict):
                detail = (
                    payload.get("message")
                    or payload.get("error")
                    or payload.get("code")
                )
                if detail:
                    raise RuntimeError(str(detail)) from exc
            raise RuntimeError(message) from exc
    except requests.exceptions.Timeout as exc:
        logging.warning(
            "Qobuz %s search timed out for query %r.",
            kind,
            query,
        )
        raise RuntimeError("Qobuz search timed out.") from exc
    except Exception as exc:  # pragma: no cover - network failure
        logging.exception(
            "Unexpected error during Qobuz %s search for query %r.",
            kind,
            query,
        )
        raise RuntimeError("Unable to reach Qobuz search endpoint.") from exc


def _qobuz_artist_search(query: str, limit: int = 10) -> List[Dict[str, str]]:
    data = _qobuz_search("artist", query, limit=limit)

    artists = data.get("artists", {}) or {}
    items = artists.get("items") or []
    results: List[Dict[str, str]] = []
    for item in items:
        artist_id = item.get("id")
        name = item.get("name") or item.get("title")
        if not artist_id or not name:
            continue

        artist_id_str = str(artist_id)
        name_str = str(name)
        image_url = _pick_first_url(
            item.get("image"),
            item.get("images"),
            item.get("picture"),
        )
        cached_url = _ensure_artist_photo(artist_id_str, image_url)

        results.append(
            {
                "id": artist_id_str,
                "name": name_str,
                "image": image_url,
                "photo": cached_url,
            }
        )

    logging.info(
        "Qobuz artist search for query %r returned %s result(s).",
        query,
        len(results),
    )
    return results


def _pick_first_str(*candidates: Any) -> str:
    for candidate in candidates:
        if isinstance(candidate, str):
            text = candidate.strip()
            if text:
                return text
        elif isinstance(candidate, dict):
            potential = (
                candidate.get("name")
                or candidate.get("title")
                or candidate.get("display_name")
            )
            if isinstance(potential, str):
                text = potential.strip()
                if text:
                    return text
        elif isinstance(candidate, list):
            for item in candidate:
                text = _pick_first_str(item)
                if text:
                    return text
    return ""


def _qobuz_album_search(query: str, limit: int = 10) -> List[Dict[str, str]]:
    data = _qobuz_search("album", query, limit=limit)

    albums = data.get("albums", {}) or {}
    items = albums.get("items") or []
    results: List[Dict[str, str]] = []
    for item in items:
        album_id = item.get("id")
        title_raw = item.get("title") or item.get("name")
        if not album_id or not title_raw:
            continue

        title = str(title_raw).strip()
        artist_name = _pick_first_str(
            item.get("artist"),
            item.get("artists"),
            item.get("performer"),
        )

        release_date = _pick_first_str(
            item.get("release_date_original"),
            item.get("release_date"),
        )
        year = ""
        if release_date:
            candidate = release_date[:4]
            if candidate.isdigit():
                year = candidate

        artist_label = artist_name
        value_parts = [part for part in [artist_name, title] if part]
        value = " - ".join(value_parts) if value_parts else title
        lookup = " ".join(part for part in [title, artist_name] if part) or title

        image_url = _pick_first_url(
            item.get("image"),
            item.get("images"),
            item.get("cover"),
            item.get("picture"),
        )

        cached_url = _ensure_album_photo(str(album_id), image_url)

        results.append(
            {
                "id": str(album_id),
                "title": title,
                "artist": artist_label,
                "year": year,
                "value": value,
                "lookup": lookup,
                "image": image_url,
                "photo": cached_url,
            }
        )

    logging.info(
        "Qobuz album search for query %r returned %s result(s).",
        query,
        len(results),
    )
    return results


def _qobuz_track_search(query: str, limit: int = 10) -> List[Dict[str, str]]:
    data = _qobuz_search("track", query, limit=limit)

    tracks = data.get("tracks", {}) or {}
    items = tracks.get("items") or []
    results: List[Dict[str, str]] = []
    for item in items:
        track_id = item.get("id")
        title_raw = item.get("title") or item.get("name")
        if not track_id or not title_raw:
            continue

        title = str(title_raw).strip()
        album_raw = item.get("album")
        album_info = album_raw or {}
        album_title = _pick_first_str(
            album_info.get("title") if isinstance(album_info, dict) else album_info,
            item.get("album_title"),
        )
        artist_name = _pick_first_str(
            item.get("performer"),
            item.get("artist"),
            item.get("contributors"),
        )

        base_value_parts = [part for part in [artist_name, title] if part]
        base_value = " - ".join(base_value_parts) if base_value_parts else title
        value = base_value
        if album_title:
            value = f"{base_value} ({album_title})" if base_value else album_title

        lookup = " ".join(
            part for part in [title, artist_name, album_title] if part
        ) or title

        album_data = album_raw if isinstance(album_raw, dict) else None
        image_url = _pick_first_url(
            item.get("image"),
            item.get("images"),
            item.get("cover"),
            item.get("picture"),
            album_data.get("image") if album_data else None,
            album_data.get("images") if album_data else None,
            album_data.get("cover") if album_data else None,
            album_data.get("picture") if album_data else None,
        )

        album_id = ""
        if isinstance(album_data, dict):
            raw_album_id = album_data.get("id")
            if raw_album_id:
                album_id = str(raw_album_id)

        cached_url = _ensure_album_photo(album_id, image_url) if album_id else ""

        results.append(
            {
                "id": str(track_id),
                "title": title,
                "album": album_title,
                "artist": artist_name,
                "value": value,
                "lookup": lookup,
                "image": image_url,
                "photo": cached_url,
                "album_id": album_id,
            }
        )

    logging.info(
        "Qobuz track search for query %r returned %s result(s).",
        query,
        len(results),
    )
    return results


def ensure_lists_exist() -> None:
    LISTS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        _ensure_database_ready_locked()


def read_entries(kind: str) -> List[Dict[str, str]]:
    if kind not in LIST_LABELS:
        return []

    if kind == "artist":
        with _lock:
            return _read_artist_entries_locked()

    table_mapping: Dict[str, Tuple[str, Tuple[str, ...]]] = {
        "album": ("albums", ("id", "title", "artist", "last_checked_at")),
        "track": ("tracks", ("id", "title", "artist", "album", "last_checked_at")),
    }
    if kind not in table_mapping:
        return []

    table_name, columns = table_mapping[kind]
    query = f"SELECT {', '.join(columns)} FROM {table_name} ORDER BY created_at, rowid"

    with _lock:
        _ensure_database_ready_locked()
        conn = _get_database_connection()
        try:
            rows = conn.execute(query).fetchall()
        finally:
            conn.close()

    entries: List[Dict[str, str]] = []
    for row in rows:
        entry: Dict[str, str] = {}
        for column in columns:
            if isinstance(row, sqlite3.Row):
                value = row[column]
            else:  # pragma: no cover - legacy tuple rows
                idx = columns.index(column)
                value = row[idx]
            entry[column] = str(value or "").strip()
        entries.append(entry)
    return entries


def add_entry(
    kind: str,
    value: str,
    *,
    display_name: str | None = None,
    artist_name: str | None = None,
    album_title: str | None = None,
) -> Tuple[bool, str]:
    value = value.strip()
    if not value:
        return False, "Value cannot be empty."

    if kind not in LIST_LABELS:
        return False, "Unknown list type."

    if kind == "artist":
        artist_id = value
        artist_label = (display_name or "").strip() or artist_id
        with _lock:
            _ensure_database_ready_locked()
            conn = _get_database_connection()
            try:
                existing = conn.execute(
                    "SELECT 1 FROM artists WHERE id = ?",
                    (artist_id,),
                ).fetchone()
                if existing:
                    return False, f"{LIST_LABELS[kind][:-1]} already present."
                conn.execute(
                    "INSERT INTO artists (id, name) VALUES (?, ?)",
                    (artist_id, artist_label),
                )
                conn.commit()
            finally:
                conn.close()

        message = f"Added {LIST_LABELS[kind][:-1]} '{artist_label}'."
        _publish_discord_event(
            "list_entry_added",
            message,
            details={
                "list": kind,
                "id": artist_id,
                "label": artist_label,
            },
        )
        return True, message

    artist = ""
    album = ""

    with _lock:
        _ensure_database_ready_locked()
        conn = _get_database_connection()
        try:
            if kind == "album":
                title = (display_name or "").strip()
                artist = (artist_name or "").strip()
                existing = conn.execute(
                    "SELECT 1 FROM albums WHERE id = ?",
                    (value,),
                ).fetchone()
                if existing:
                    return False, f"{LIST_LABELS[kind][:-1]} already present."
                conn.execute(
                    "INSERT INTO albums (id, title, artist) VALUES (?, ?, ?)",
                    (value, title, artist),
                )
                conn.commit()
                label = title or value
            elif kind == "track":
                title = (display_name or "").strip()
                artist = (artist_name or "").strip()
                album = (album_title or "").strip()
                existing = conn.execute(
                    "SELECT 1 FROM tracks WHERE id = ?",
                    (value,),
                ).fetchone()
                if existing:
                    return False, f"{LIST_LABELS[kind][:-1]} already present."
                conn.execute(
                    "INSERT INTO tracks (id, title, artist, album) VALUES (?, ?, ?, ?)",
                    (value, title, artist, album),
                )
                conn.commit()
                label = title or value
            else:  # pragma: no cover - unsupported kind
                return False, "Unknown list type."
        finally:
            conn.close()

    message = f"Added {LIST_LABELS[kind][:-1]} '{label}'."
    details = {"list": kind, "id": value, "label": label}
    if kind == "album" and artist:
        details["artist"] = artist
    if kind == "track":
        if artist:
            details["artist"] = artist
        if album:
            details["album"] = album
    _publish_discord_event("list_entry_added", message, details=details)
    return True, message


def sanitize_entry_value(value: str) -> str | None:
    """Replicate the scheduler's trimming and comment filtering."""

    sanitized = value.strip()
    if not sanitized or sanitized.startswith("#"):
        return None
    return sanitized


def _enqueue_async_message(message: str, is_error: bool) -> None:
    with _async_lock:
        _async_messages.append((message, is_error))

    notify = is_error
    event = "async_error" if is_error else "async_info"
    level = "error" if is_error else "info"

    lower = message.lower()
    if not notify and lower.startswith("download completed"):
        notify = True
        event = "download_completed"
        level = "success"
    elif is_error and lower.startswith("download failed"):
        event = "download_failed"

    if notify:
        _publish_discord_event(event, message, level=level)


def _consume_async_messages() -> List[Tuple[str, bool]]:
    with _async_lock:
        if not _async_messages:
            return []
        messages = list(_async_messages)
        _async_messages.clear()
        return messages


def _orpheus_worker_main() -> None:
    while True:
        label, task = _orpheus_queue.get()
        try:
            logging.debug("Running queued Orpheus task: %s", label)
            task()
        except Exception:  # pragma: no cover - worker guard
            logging.exception(
                "Unexpected error while running queued Orpheus task %s.",
                label,
            )
        finally:
            _orpheus_queue.task_done()


def _ensure_orpheus_worker() -> None:
    global _orpheus_worker
    with _orpheus_worker_lock:
        if _orpheus_worker and _orpheus_worker.is_alive():
            return
        _orpheus_worker = threading.Thread(
            target=_orpheus_worker_main,
            name="orpheus-runner",
            daemon=True,
        )
        _orpheus_worker.start()


def _queue_orpheus_task(label: str, task: Callable[[], None]) -> None:
    _ensure_orpheus_worker()
    logging.info("Queued Orpheus command: %s", label)
    _orpheus_queue.put((label, task))


def _run_artist_download(artist_id: str) -> None:
    command = [
        "python3",
        "-u",
        "orpheus.py",
        "download",
        "qobuz",
        "artist",
        artist_id,
    ]
    logging.info("Starting one-time Qobuz download for artist %s.", artist_id)
    try:
        result = subprocess.run(
            command,
            cwd="/orpheusdl",
            check=False,
        )
    except Exception as exc:  # pragma: no cover - subprocess failure
        logging.exception("Failed to launch download for artist %s.", artist_id)
        _enqueue_async_message(
            f"Download failed for artist {artist_id}: {exc}",
            True,
        )
        return

    if result.returncode != 0:
        logging.error(
            "Download command exited with %s for artist %s. See docker logs for output.",
            result.returncode,
            artist_id,
        )
        _enqueue_async_message(
            f"Download failed for artist {artist_id}: exit code {result.returncode}. Check logs for details.",

            True,
        )
    else:
        logging.info("Download completed successfully for artist %s.", artist_id)
        _enqueue_async_message(
            f"Download completed for artist {artist_id}.",
            False,
        )


def _trigger_artist_download(artist_id: str) -> None:
    sanitized = sanitize_entry_value(artist_id)
    if sanitized is None:
        logging.warning(
            "Skipping download trigger for invalid artist id: %r", artist_id
        )
        return

    _queue_orpheus_task(
        f"download artist {sanitized}",
        functools.partial(_run_artist_download, sanitized),
    )


def _run_download(kind: str, value: str) -> None:
    command = [
        "python3",
        "-u",
        "orpheus.py",
        "download",
        "qobuz",
        kind,
        value,
    ]
    logging.info("Starting download for %s: %s", kind, value)
    try:
        result = subprocess.run(
            command,
            cwd="/orpheusdl",
            check=False,
        )
    except Exception as exc:  # pragma: no cover - subprocess failure
        logging.exception("Failed to launch download for %s: %s", kind, value)
        _enqueue_async_message(
            f"Download failed for {LIST_LABELS[kind][:-1]} '{value}': {exc}",
            True,
        )
        return

    if result.returncode != 0:
        logging.error(
            "Download exited with %s for %s:%s. See docker logs for output.",
            result.returncode,
            kind,
            value,
        )
        _enqueue_async_message(
            f"Download failed for {LIST_LABELS[kind][:-1]} '{value}': exit code {result.returncode}. Check logs for details.",
            True,
        )
    else:
        logging.info("Download succeeded for %s: %s", kind, value)


def _trigger_download(kind: str, value: str) -> None:
    sanitized = sanitize_entry_value(value)
    if sanitized is None:
        logging.info(
            "Skipping download for %s entry %r due to scheduler sanitisation.",
            kind,
            value,
        )
        if value.startswith("#"):
            _enqueue_async_message(
                f"Entry '{value}' added to {LIST_LABELS[kind]} but ignored because it starts with '#'.",
                False,
            )
        return

    _queue_orpheus_task(
        f"download {kind} {sanitized}",
        functools.partial(_run_download, kind, sanitized),
    )


def remove_entry(kind: str, index: int) -> Tuple[bool, str]:
    if kind not in LIST_LABELS:
        return False, "Unknown list type."

    if kind == "artist":
        with _lock:
            _ensure_database_ready_locked()
            conn = _get_database_connection()
            try:
                row = conn.execute(
                    "SELECT rowid AS rid, id, name FROM artists ORDER BY created_at, rowid LIMIT 1 OFFSET ?",
                    (index,),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            return False, "Entry not found."

        artist_rowid = ((row["rid"] if isinstance(row, sqlite3.Row) else row[0]) or 0)
        artist_id = ((row["id"] if isinstance(row, sqlite3.Row) else row[1]) or "").strip()
        artist_name = ((row["name"] if isinstance(row, sqlite3.Row) else row[2]) or "").strip()

        with _lock:
            _ensure_database_ready_locked()
            conn = _get_database_connection()
            try:
                conn.execute("DELETE FROM artists WHERE rowid = ?", (artist_rowid,))
                conn.commit()
            finally:
                conn.close()

        if artist_name:
            _delete_artist_directory(artist_name)

        removed_label = artist_name or artist_id
        message = f"Removed {LIST_LABELS[kind][:-1]} '{removed_label}'."
        _publish_discord_event(
            "list_entry_removed",
            message,
            details={
                "list": kind,
                "id": artist_id,
                "label": removed_label,
            },
        )
        return True, message

    if kind == "album":
        with _lock:
            _ensure_database_ready_locked()
            conn = _get_database_connection()
            try:
                row = conn.execute(
                    "SELECT rowid AS rid, id, title, artist FROM albums ORDER BY created_at, rowid LIMIT 1 OFFSET ?",
                    (index,),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            return False, "Entry not found."

        album_rowid = ((row["rid"] if isinstance(row, sqlite3.Row) else row[0]) or 0)
        album_id = ((row["id"] if isinstance(row, sqlite3.Row) else row[1]) or "").strip()
        album_title = ((row["title"] if isinstance(row, sqlite3.Row) else row[2]) or "").strip()
        album_artist = ((row["artist"] if isinstance(row, sqlite3.Row) else row[3]) or "").strip()

        can_remove, messages = _remove_album_media(album_artist, album_title)
        primary_message = ""
        for text, is_error in messages:
            _enqueue_async_message(text, is_error)
            if not primary_message:
                primary_message = text
        if not can_remove:
            return False, primary_message or "Album media removal skipped."

        with _lock:
            _ensure_database_ready_locked()
            conn = _get_database_connection()
            try:
                conn.execute("DELETE FROM albums WHERE rowid = ?", (album_rowid,))
                conn.commit()
            finally:
                conn.close()

        removed_label = album_title or album_id
        message = f"Removed {LIST_LABELS[kind][:-1]} '{removed_label}'."
        details = {
            "list": kind,
            "id": album_id,
            "label": removed_label,
        }
        if album_artist:
            details["artist"] = album_artist
        _publish_discord_event("list_entry_removed", message, details=details)
        return True, message

    if kind == "track":
        with _lock:
            _ensure_database_ready_locked()
            conn = _get_database_connection()
            try:
                row = conn.execute(
                    "SELECT rowid AS rid, id, title, artist, album FROM tracks ORDER BY created_at, rowid LIMIT 1 OFFSET ?",
                    (index,),
                ).fetchone()
            finally:
                conn.close()
        if row is None:
            return False, "Entry not found."

        track_rowid = ((row["rid"] if isinstance(row, sqlite3.Row) else row[0]) or 0)
        track_id = ((row["id"] if isinstance(row, sqlite3.Row) else row[1]) or "").strip()
        track_title = ((row["title"] if isinstance(row, sqlite3.Row) else row[2]) or "").strip()
        track_artist = ((row["artist"] if isinstance(row, sqlite3.Row) else row[3]) or "").strip()
        track_album = ((row["album"] if isinstance(row, sqlite3.Row) else row[4]) or "").strip()

        can_remove, messages = _remove_track_media(track_artist, track_album, track_title)
        primary_message = ""
        for text, is_error in messages:
            _enqueue_async_message(text, is_error)
            if not primary_message:
                primary_message = text
        if not can_remove:
            return False, primary_message or "Track removal skipped."

        with _lock:
            _ensure_database_ready_locked()
            conn = _get_database_connection()
            try:
                conn.execute("DELETE FROM tracks WHERE rowid = ?", (track_rowid,))
                conn.commit()
            finally:
                conn.close()

        removed_label = track_title or track_id
        message = f"Removed {LIST_LABELS[kind][:-1]} '{removed_label}'."
        details = {
            "list": kind,
            "id": track_id,
            "label": removed_label,
        }
        if track_artist:
            details["artist"] = track_artist
        if track_album:
            details["album"] = track_album
        _publish_discord_event("list_entry_removed", message, details=details)
        return True, message

    return False, "Entry not found."


def normalize_kind(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.lower().strip()
    if key.endswith("s"):
        key = key[:-1]
    return key if key in LIST_LABELS else None


def redirect_location(
    message: str | None = None,
    is_error: bool = False,
    *,
    selected: str | None = None,
) -> str:
    params: Dict[str, str] = {}
    if message:
        params["message"] = message
    if is_error:
        params["error"] = "1"
    selected_kind = normalize_kind(selected) if selected else None
    if selected_kind:
        params["list"] = selected_kind
    if not params:
        return "/"
    return "/?" + urlencode(params)


class ListRequestHandler(BaseHTTPRequestHandler):
    server_version = "OrpheusListHTTP/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/artist-search":
            self.handle_artist_search(parsed)
            return

        if parsed.path == "/api/album-search":
            self.handle_album_search(parsed)
            return

        if parsed.path == "/api/track-search":
            self.handle_track_search(parsed)
            return

        if parsed.path.startswith("/photos/"):
            self.handle_photo_request(parsed)
            return

        if parsed.path not in {"", "/"}:
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        query = parse_qs(parsed.query)
        message = query.get("message", [None])[0]
        is_error = query.get("error", ["0"])[0] == "1"
        selected = normalize_kind(query.get("list", [None])[0]) or "artist"

        body = self.render_index(
            message=message,
            is_error=is_error,
            selected_kind=selected,
        )
        body_bytes = body.encode("utf-8")

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        content_length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(content_length).decode("utf-8") if content_length else ""
        if parsed.path == "/api/artist-select":
            self.handle_artist_select(payload, self.headers.get("Content-Type", ""))
            return

        if parsed.path == "/api/album-select":
            self.handle_album_select(payload, self.headers.get("Content-Type", ""))
            return

        if parsed.path == "/api/track-select":
            self.handle_track_select(payload, self.headers.get("Content-Type", ""))
            return

        data = {k: v[0] for k, v in parse_qs(payload).items() if v}

        if parsed.path == "/download-photos":
            self.handle_download_photos(data)
            return

        if parsed.path == "/purge-photos":
            self.handle_purge_photos(data)
            return

        if parsed.path == "/delete":
            self.handle_delete(data)
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def handle_photo_request(self, parsed) -> None:
        identifier = parsed.path[len("/photos/"):]
        identifier = unquote(identifier or "")
        normalized = _normalize_photo_identifier(identifier)
        if not normalized:
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        path = _photo_file_path(normalized)
        with _photo_lock:
            if not path.exists() or not path.is_file():
                self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
                return
            try:
                data = path.read_bytes()
            except OSError as exc:
                logging.warning(
                    "Failed to read cached photo %s: %s.",
                    path,
                    exc,
                )
                self.send_error(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    "Failed to read cached photo.",
                )
                return

        if not data:
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        mime_type = _detect_photo_mime(data)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.send_header("Content-Disposition", "inline")
        self.end_headers()
        self.wfile.write(data)

    def handle_artist_search(self, parsed) -> None:
        params = parse_qs(parsed.query)
        query = (params.get("q") or [""])[0].strip()
        limit_raw = (params.get("limit") or ["10"])[0]
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 10

        logging.info(
            "Received artist search request from %s with query=%r limit=%s.",
            self.address_string(),
            query,
            limit,
        )
        if not query:
            self.send_json({"error": "Missing search query."}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            results = _qobuz_artist_search(query, limit=limit)
        except RuntimeError as exc:
            message = str(exc)
            status = HTTPStatus.SERVICE_UNAVAILABLE if "app_id" in message else HTTPStatus.BAD_GATEWAY
            logging.warning(
                "Artist search request for query %r failed with status %s: %s",
                query,
                status,
                message,
            )
            self.send_json({"error": message}, status=status)
            return

        logging.info(
            "Artist search request for query %r returning %s result(s) to client.",
            query,
            len(results),
        )
        self.send_json({"results": results})

    def handle_album_search(self, parsed) -> None:
        params = parse_qs(parsed.query)
        query = (params.get("q") or [""])[0].strip()
        limit_raw = (params.get("limit") or ["10"])[0]
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 10

        logging.info(
            "Received album search request from %s with query=%r limit=%s.",
            self.address_string(),
            query,
            limit,
        )
        if not query:
            self.send_json({"error": "Missing search query."}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            results = _qobuz_album_search(query, limit=limit)
        except RuntimeError as exc:
            message = str(exc)
            status = (
                HTTPStatus.SERVICE_UNAVAILABLE
                if "app_id" in message
                else HTTPStatus.BAD_GATEWAY
            )
            logging.warning(
                "Album search request for query %r failed with status %s: %s",
                query,
                status,
                message,
            )
            self.send_json({"error": message}, status=status)
            return

        logging.info(
            "Album search request for query %r returning %s result(s) to client.",
            query,
            len(results),
        )
        self.send_json({"results": results})

    def handle_track_search(self, parsed) -> None:
        params = parse_qs(parsed.query)
        query = (params.get("q") or [""])[0].strip()
        limit_raw = (params.get("limit") or ["10"])[0]
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 10

        logging.info(
            "Received track search request from %s with query=%r limit=%s.",
            self.address_string(),
            query,
            limit,
        )
        if not query:
            self.send_json({"error": "Missing search query."}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            results = _qobuz_track_search(query, limit=limit)
        except RuntimeError as exc:
            message = str(exc)
            status = (
                HTTPStatus.SERVICE_UNAVAILABLE
                if "app_id" in message
                else HTTPStatus.BAD_GATEWAY
            )
            logging.warning(
                "Track search request for query %r failed with status %s: %s",
                query,
                status,
                message,
            )
            self.send_json({"error": message}, status=status)
            return

        logging.info(
            "Track search request for query %r returning %s result(s) to client.",
            query,
            len(results),
        )
        self.send_json({"results": results})

    def handle_artist_select(self, raw_body: str, content_type: str | None) -> None:
        content_type = (content_type or "").split(";", 1)[0].strip().lower()
        data: Dict[str, str] = {}

        if content_type == "application/json":
            try:
                payload = json.loads(raw_body or "{}")
            except json.JSONDecodeError:
                self.send_json(
                    {"error": "Invalid JSON body."},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return

            if isinstance(payload, dict):
                for key, value in payload.items():
                    if value is None:
                        data[str(key)] = ""
                    elif isinstance(value, (str, int, float)):
                        data[str(key)] = str(value)
                    else:
                        data[str(key)] = ""
            else:
                self.send_json(
                    {"error": "Invalid request payload."},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
        else:
            data = {k: v[0] for k, v in parse_qs(raw_body).items() if v}

        artist_id = data.get("id", "").strip()
        artist_name = data.get("name", "").strip()

        logging.info(
            "Received artist selection from %s with id=%r name=%r.",
            self.address_string(),
            artist_id,
            artist_name,
        )

        if not artist_id:
            self.send_json(
                {"error": "Missing artist id."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return
          
        success, add_message = add_entry(
            "artist", artist_id, display_name=artist_name
        )

        if not success:
            self.send_json({"error": add_message}, status=HTTPStatus.CONFLICT)
            return

        logging.info("Artist %s added to list: %s", artist_id, add_message)
        _trigger_artist_download(artist_id)

        if artist_name and artist_name != artist_id:
            combined_message = (
                f"Added artist '{artist_name}' (ID {artist_id}) and queued download."
            )
        else:
            combined_message = (
                f"Added artist ID {artist_id} and queued download."
            )

        redirect = redirect_location(
            message=combined_message,
            is_error=False,
            selected="artist",
        )
        self.send_json(
            {
                "success": True,
                "message": combined_message,
                "redirect": redirect,
            }
        )

    def handle_album_select(self, raw_body: str, content_type: str | None) -> None:
        content_type = (content_type or "").split(";", 1)[0].strip().lower()
        data: Dict[str, str] = {}

        if content_type == "application/json":
            try:
                payload = json.loads(raw_body or "{}")
            except json.JSONDecodeError:
                self.send_json(
                    {"error": "Invalid JSON body."},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return

            if isinstance(payload, dict):
                for key, value in payload.items():
                    if value is None:
                        data[str(key)] = ""
                    elif isinstance(value, (str, int, float)):
                        data[str(key)] = str(value)
                    else:
                        data[str(key)] = ""
            else:
                self.send_json(
                    {"error": "Invalid request payload."},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
        else:
            data = {k: v[0] for k, v in parse_qs(raw_body).items() if v}

        album_id = data.get("id", "").strip()
        album_title = data.get("title", "").strip()
        album_artist = data.get("artist", "").strip()
        stored_value = data.get("value", "").strip()
        album_photo = data.get("photo", "").strip()
        album_image = data.get("image", "").strip()

        logging.info(
            "Received album selection from %s with id=%r title=%r artist=%r.",
            self.address_string(),
            album_id,
            album_title,
            album_artist,
        )

        if not album_id:
            album_id = stored_value

        if not album_id:
            self.send_json(
                {"error": "Missing album identifier."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        label_value = album_title or stored_value or album_id

        if album_id:
            _ensure_album_photo(album_id, album_photo or album_image)

        success, add_message = add_entry(
            "album",
            album_id,
            display_name=label_value,
            artist_name=album_artist,
        )

        if not success:
            self.send_json({"error": add_message}, status=HTTPStatus.CONFLICT)
            return

        logging.info("Album %s added to list: %s", album_id, add_message)
        _trigger_download("album", album_id)

        label = album_title or label_value
        if album_artist and album_title:
            combined_message = (
                f"Added album '{album_title}' by {album_artist} and queued download."
            )
        elif album_artist:
            combined_message = (
                f"Added album by {album_artist} and queued download."
            )
        else:
            combined_message = f"Added album '{label}' and queued download."

        redirect = redirect_location(
            message=combined_message,
            is_error=False,
            selected="album",
        )
        self.send_json(
            {
                "success": True,
                "message": combined_message,
                "redirect": redirect,
            }
        )

    def handle_track_select(self, raw_body: str, content_type: str | None) -> None:
        content_type = (content_type or "").split(";", 1)[0].strip().lower()
        data: Dict[str, str] = {}

        if content_type == "application/json":
            try:
                payload = json.loads(raw_body or "{}")
            except json.JSONDecodeError:
                self.send_json(
                    {"error": "Invalid JSON body."},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return

            if isinstance(payload, dict):
                for key, value in payload.items():
                    if value is None:
                        data[str(key)] = ""
                    elif isinstance(value, (str, int, float)):
                        data[str(key)] = str(value)
                    else:
                        data[str(key)] = ""
            else:
                self.send_json(
                    {"error": "Invalid request payload."},
                    status=HTTPStatus.BAD_REQUEST,
                )
                return
        else:
            data = {k: v[0] for k, v in parse_qs(raw_body).items() if v}

        track_id = data.get("id", "").strip()
        track_title = data.get("title", "").strip()
        album_title = data.get("album", "").strip()
        artist_name = data.get("artist", "").strip()
        stored_value = data.get("value", "").strip()
        album_id = data.get("album_id", "").strip()
        album_photo = data.get("photo", "").strip()
        album_image = data.get("image", "").strip()

        logging.info(
            "Received track selection from %s with id=%r title=%r album=%r artist=%r.",
            self.address_string(),
            track_id,
            track_title,
            album_title,
            artist_name,
        )

        if not track_id:
            track_id = stored_value

        if not track_id:
            self.send_json(
                {"error": "Missing track identifier."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        label_value = track_title or stored_value or track_id

        if album_id:
            _ensure_album_photo(album_id, album_photo or album_image)

        success, add_message = add_entry(
            "track",
            track_id,
            display_name=label_value,
            artist_name=artist_name,
            album_title=album_title,
        )

        if not success:
            self.send_json({"error": add_message}, status=HTTPStatus.CONFLICT)
            return

        logging.info("Track %s added to list: %s", track_id, add_message)
        _trigger_download("track", track_id)

        label = track_title or label_value
        pieces = [f"Added track '{label}'"]
        if artist_name:
            pieces.append(f"by {artist_name}")
        if album_title:
            pieces.append(f"from album '{album_title}'")
        combined_message = " ".join(pieces) + " and queued download."

        redirect = redirect_location(
            message=combined_message,
            is_error=False,
            selected="track",
        )
        self.send_json(
            {
                "success": True,
                "message": combined_message,
                "redirect": redirect,
            }
        )

    def handle_purge_photos(self, data: Dict[str, str]) -> None:
        selected = normalize_kind(data.get("selected")) or "artist"
        removed = purge_cached_photos()
        logging.info("Photo purge requested by %s removed %s file(s).", self.address_string(), removed)
        if removed:
            message = f"Removed {removed} cached photo{'s' if removed != 1 else ''}."
        else:
            message = "No cached photos found."
        self.redirect_home(message, is_error=False, selected=selected)

    def handle_download_photos(self, data: Dict[str, str]) -> None:
        selected = normalize_kind(data.get("selected")) or "artist"
        try:
            artist_count, album_count, extra_messages = download_missing_photos()
        except RuntimeError as exc:
            logging.warning(
                "Download images request from %s failed: %s.",
                self.address_string(),
                exc,
            )
            self.redirect_home(str(exc), is_error=True, selected=selected)
            return

        for text, is_error in extra_messages:
            _enqueue_async_message(text, is_error)

        parts: List[str] = []
        if artist_count:
            parts.append(
                f"{artist_count} artist photo{'s' if artist_count != 1 else ''}"
            )
        if album_count:
            parts.append(
                f"{album_count} album cover{'s' if album_count != 1 else ''}"
            )

        if parts:
            message = "Downloaded " + " and ".join(parts) + "."
        else:
            message = "No missing images were found."

        logging.info(
            "Download images request from %s completed: %s artist photo(s), %s album cover(s).",
            self.address_string(),
            artist_count,
            album_count,
        )
        self.redirect_home(message, is_error=False, selected=selected)

    def handle_delete(self, data: Dict[str, str]) -> None:
        kind = normalize_kind(data.get("list"))
        if not kind:
            self.redirect_home("Unknown list type.", is_error=True)
            return
        selected = normalize_kind(data.get("selected")) or kind
        try:
            index = int(data.get("index", ""))
        except ValueError:
            self.redirect_home("Invalid entry index.", is_error=True)
            return
        success, message = remove_entry(kind, index)
        self.redirect_home(message, is_error=not success, selected=selected)

    def redirect_home(
        self,
        message: str | None,
        is_error: bool = False,
        *,
        selected: str | None = None,
    ) -> None:
        location = redirect_location(
            message=message,
            is_error=is_error,
            selected=selected,
        )
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()



    def render_index(
        self,
        message: str | None,
        is_error: bool,
        *,
        selected_kind: str,
    ) -> str:
        normalized_selected = normalize_kind(selected_kind) or "artist"
        escaped_selected = html.escape(normalized_selected)

        sections: List[str] = []
        for kind, label in LIST_LABELS.items():
            entries = read_entries(kind)
            row_items: List[str] = []
            for idx, entry in enumerate(entries):
                remove_form = ''.join(
                    [
                        '<form method="post" action="/delete" class="inline-form">',
                        f'<input type="hidden" name="list" value="{kind}">',
                        f'<input type="hidden" name="selected" value="{kind}">',
                        f'<input type="hidden" name="index" value="{idx}">',
                        '<button type="submit" class="button danger">Remove</button>',
                        '</form>',
                    ]
                )

                primary_text = ""
                secondary_html = ""

                if isinstance(entry, dict):
                    entry_id = (entry.get("id") or "").strip()
                    last_checked_raw = str(entry.get("last_checked_at") or "").strip()
                    last_checked_label = last_checked_raw or "Never"
                    separator = " &bull; "
                    if kind == "artist":
                        artist_name = (entry.get("name") or "").strip()
                        primary_text = artist_name or entry_id
                        secondary_parts: List[str] = []
                        if entry_id:
                            secondary_parts.append(f"ID: {html.escape(entry_id)}")
                        secondary_parts.append(
                            f"Last checked: {html.escape(last_checked_label)}"
                        )
                        if secondary_parts:
                            secondary_html = (
                                f'<span class="entry-secondary">{separator.join(secondary_parts)}</span>'
                            )
                    elif kind == "album":
                        title = (entry.get("title") or "").strip()
                        artist_name = (entry.get("artist") or "").strip()
                        primary_text = title or entry_id
                        secondary_parts: List[str] = []
                        if artist_name:
                            secondary_parts.append(f"Artist: {html.escape(artist_name)}")
                        if entry_id:
                            secondary_parts.append(f"ID: {html.escape(entry_id)}")
                        secondary_parts.append(
                            f"Last checked: {html.escape(last_checked_label)}"
                        )
                        if secondary_parts:
                            secondary_html = (
                                f'<span class="entry-secondary">{separator.join(secondary_parts)}</span>'
                            )
                    elif kind == "track":
                        title = (entry.get("title") or "").strip()
                        artist_name = (entry.get("artist") or "").strip()
                        album_title = (entry.get("album") or "").strip()
                        primary_text = title or entry_id
                        secondary_parts: List[str] = []
                        if artist_name and album_title:
                            secondary_parts.append(
                                f"{html.escape(artist_name)} - {html.escape(album_title)}"
                            )
                        elif artist_name:
                            secondary_parts.append(html.escape(artist_name))
                        elif album_title:
                            secondary_parts.append(html.escape(album_title))
                        if entry_id:
                            secondary_parts.append(f"ID: {html.escape(entry_id)}")
                        secondary_parts.append(
                            f"Last checked: {html.escape(last_checked_label)}"
                        )
                        if secondary_parts:
                            secondary_html = (
                                f'<span class="entry-secondary">{separator.join(secondary_parts)}</span>'
                            )
                    else:  # pragma: no cover - unexpected dict entry
                        primary_text = str(entry)
                if not primary_text:
                    primary_text = str(entry)

                entry_primary = html.escape(primary_text)
                alt_label = primary_text or entry_id or LIST_LABELS[kind][:-1]
                image_html = ""
                image_url = ""
                alt_suffix = ""
                if kind == "artist" and entry_id:
                    image_url = _cached_artist_photo_url(entry_id)
                    alt_suffix = "photo"
                elif kind == "album" and entry_id:
                    image_url = _cached_album_photo_url(entry_id)
                    alt_suffix = "cover"

                if image_url:
                    alt_text = " ".join(part for part in [alt_label, alt_suffix] if part).strip()
                    if not alt_text:
                        alt_text = alt_suffix or LIST_LABELS[kind][:-1]
                    image_html = ''.join(
                        [
                            '<div class="entry-thumb">',
                            f'<img src="{html.escape(image_url)}" alt="{html.escape(alt_text)}" loading="lazy">',
                            '</div>',
                        ]
                    )

                row_parts = ['<li class="entry">']
                if image_html:
                    row_parts.append(image_html)
                row_parts.extend(
                    [
                        '<div class="entry-text">',
                        f'<span class="entry-primary">{entry_primary}</span>',
                        secondary_html,
                        '</div>',
                        remove_form,
                        '</li>',
                    ]
                )
                row_items.append(''.join(row_parts))

            rows_html = (
                '\n'.join(row_items)
                if row_items
                else '<li class=\"empty\">No entries yet.</li>'
            )

            active_class = ' active' if kind == normalized_selected else ''
            search_block = ''
            if kind == 'artist':
                search_block = ARTIST_SEARCH_SECTION
            elif kind == 'album':
                search_block = ALBUM_SEARCH_SECTION
            elif kind == 'track':
                search_block = TRACK_SEARCH_SECTION

            section_parts = [
                f'<section class="list-section{active_class}" data-list="{kind}">',
                '<div class="section-header">',
                f'<h2>{html.escape(label)}</h2>',
                '</div>',
                search_block,
                f'<ul class="entry-list">{rows_html}</ul>',
            ]

            section_parts.append('</section>')
            sections.append(''.join(section_parts))

        banners: List[Tuple[str, bool]] = []
        if message:
            banners.append((message, is_error))
        banners.extend(_consume_async_messages())

        message_html = ''.join(
            f'<div class="banner {"error" if banner_is_error else "info"}">{html.escape(banner_message)}</div>'
            for banner_message, banner_is_error in banners
        )

        options_html = ''.join(
            f'<option value="{kind}"{" selected" if kind == normalized_selected else ""}>{html.escape(label)}</option>'
            for kind, label in LIST_LABELS.items()
        )
        controls_html = ''.join(
            [
                '<div class="controls">',
                '<label class="list-switcher" for="list-selector">',
                '<span class="list-switcher-label">Show list</span>',
                f'<select id="list-selector" name="list-selector">{options_html}</select>',
                '</label>',
                '<form method="post" action="/download-photos" class="inline-form download-form">',
                f'<input type="hidden" name="selected" value="{escaped_selected}">',
                '<button type="submit" class="button secondary">Download Images</button>',
                '</form>',
                '<form method="post" action="/purge-photos" class="inline-form purge-form">',
                f'<input type="hidden" name="selected" value="{escaped_selected}">',
                '<button type="submit" class="button warning">Purge Images</button>',
                '</form>',
                '</div>',
            ]
        )

        styles = ''.join(
            [
                ':root{color-scheme:dark;}',
                '*{box-sizing:border-box;}',
                "body{font-family:'Inter',Arial,sans-serif;background:#0b1320;color:#f4f6ff;margin:0;min-height:100vh;}",
                '.page{max-width:960px;margin:0 auto;padding:1.5rem clamp(1rem,4vw,2.5rem);}',
                'h1{margin:0 0 1.25rem;font-size:clamp(1.75rem,2.5vw+1rem,2.6rem);}',
                '.controls{display:flex;flex-wrap:wrap;align-items:center;gap:0.75rem;margin-bottom:1.5rem;}',
                '.list-switcher{display:flex;align-items:center;gap:0.6rem;background:#161f2f;padding:0.75rem 1rem;border-radius:10px;}',
                '.list-switcher-label{font-weight:600;font-size:0.95rem;color:#a7b4d6;}',
                '.list-switcher select{background:#0f1724;border:1px solid #2c3a55;color:#f4f6ff;padding:0.45rem 0.9rem;border-radius:6px;font-size:1rem;min-width:10rem;}',
                '.banner{margin-bottom:1rem;padding:0.9rem 1rem;border-radius:8px;border:1px solid transparent;}',
                '.banner.info{background:rgba(47,137,252,0.15);border-color:rgba(47,137,252,0.45);color:#d8e5ff;}',
                '.banner.error{background:rgba(217,83,79,0.18);border-color:rgba(217,83,79,0.55);color:#ffd7d5;}',
                '.list-section{display:none;background:#161f2f;border-radius:12px;padding:1.25rem clamp(1rem,3vw,1.75rem);margin-bottom:1.75rem;box-shadow:0 16px 28px rgba(5,10,25,0.45);}',
                '.list-section.active{display:block;}',
                '.section-header{display:flex;align-items:center;justify-content:space-between;gap:0.75rem;margin-bottom:1rem;}',
                '.section-header h2{margin:0;font-size:clamp(1.35rem,1.5vw+1rem,1.8rem);}',
                '.entry-list{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:0.75rem;}',
                '.entry{display:flex;align-items:center;justify-content:space-between;gap:0.75rem;padding:0.9rem 1rem;background:#0f1724;border:1px solid rgba(255,255,255,0.06);border-radius:10px;}',
                '.entry-thumb{flex:0 0 auto;width:72px;height:72px;border-radius:10px;overflow:hidden;background:#1b2539;display:flex;align-items:center;justify-content:center;}',
                '.entry-thumb img{width:100%;height:100%;object-fit:cover;display:block;}',
                '.entry-text{flex:1;display:flex;flex-direction:column;gap:0.3rem;}',
                '.entry-primary{font-weight:600;word-break:break-word;}',
                '.entry-secondary{font-size:0.85rem;color:#a7b4d6;word-break:break-word;}',
                '.inline-form{margin:0;}',
                '.button{display:inline-flex;align-items:center;justify-content:center;border:none;border-radius:6px;padding:0.45rem 0.95rem;font-weight:600;cursor:pointer;transition:transform 0.15s ease,filter 0.15s ease;color:#fff;}',
                '.button:hover{filter:brightness(1.08);transform:translateY(-1px);}',
                '.button:active{transform:translateY(0);}',
                '.button.primary{background:#2f89fc;}',
                '.button.success{background:#1bbf72;color:#04120a;}',
                '.button.warning{background:#f0ad4e;color:#2b1a00;}',
                '.button.danger{background:#d9534f;}',
                '.button.secondary{background:#3c4fa3;}',
                '.input-group{display:flex;flex-direction:column;gap:0.35rem;width:100%;flex:1;}',
                '.field-label{font-size:0.85rem;color:#8d99bd;text-transform:uppercase;letter-spacing:0.05em;}',
                '.search-form input[type=search],.search-form input[type=text]{background:#0b1320;border:1px solid #2c3a55;border-radius:6px;padding:0.55rem 0.75rem;color:#f4f6ff;font-size:1rem;width:100%;}',
                '.search-form input[type=search]:focus,.search-form input[type=text]:focus{outline:2px solid #2f89fc;outline-offset:0;border-color:#2f89fc;}',
                '.search-block{margin:0 0 1.25rem;display:flex;flex-direction:column;gap:0.9rem;}',
                '.search-form{display:flex;flex-direction:column;gap:0.9rem;}',
                '.search-grid{display:grid;gap:0.75rem;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));}',
                '.search-actions{display:flex;justify-content:flex-end;}',
                '.search-status{font-size:0.9rem;color:#8d99bd;display:block;}',
                '.search-results{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:0.75rem;}',
                '.search-result{display:flex;align-items:center;justify-content:space-between;gap:0.9rem;background:#0f1724;border:1px solid rgba(255,255,255,0.06);border-radius:10px;padding:0.85rem 1rem;}',
                '.search-meta{flex:1;display:flex;flex-direction:column;gap:0.3rem;}',
                '.search-primary{font-weight:600;word-break:break-word;}',
                '.search-secondary{font-size:0.85rem;color:#a7b4d6;word-break:break-word;}',
                '.search-thumb{flex:0 0 auto;width:72px;height:72px;border-radius:10px;overflow:hidden;background:#1b2539;display:flex;align-items:center;justify-content:center;}',
                '.search-thumb img{width:100%;height:100%;object-fit:cover;display:block;}',
                '.search-result .button{align-self:center;}',
                '.empty{color:#8d99bd;font-style:italic;padding:0.5rem 0;}',
                '@media (max-width:640px){.entry{flex-direction:column;align-items:stretch;}.entry-thumb{width:100%;height:auto;max-height:220px;}.entry-thumb img{width:100%;height:auto;}.inline-form{width:100%;}.inline-form .button{width:100%;}.search-result{flex-direction:column;align-items:stretch;}.search-thumb{width:100%;height:auto;max-height:220px;}.search-thumb img{width:100%;height:auto;}.search-result .button{width:100%;}.search-actions{justify-content:stretch;}.search-actions .button{width:100%;}}',
            ]
        )

        sections_html = ''.join(sections)

        return (
            '<!DOCTYPE html>'
            '<html lang="en">'
            '<head>'
            '<meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>OrpheusDL Lists</title>'
            f'<style>{styles}</style>'
            '</head>'
            '<body>'
            '<div class="page">'
            '<h1>OrpheusDL Lists</h1>'
            f'{message_html}'
            f'{controls_html}'
            f'{sections_html}'
            '</div>'
            f'{SEARCH_SCRIPT}'
            '</body>'
            '</html>'
        )

    def send_json(self, payload: Dict[str, object], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        logging.info("%s - %s", self.address_string(), format % args)


def run_server() -> None:
    ensure_lists_exist()
    server = ThreadingHTTPServer((WEB_HOST, WEB_PORT), ListRequestHandler)
    server.daemon_threads = True
    logging.info("Starting list UI on %s:%s", WEB_HOST, WEB_PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - manual stop
        pass
    finally:
        server.server_close()
        logging.info("List UI stopped")


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LISTS_WEB_LOG_LEVEL", "INFO"),
                        format="[%(asctime)s] %(levelname)s %(message)s")
    run_server()
