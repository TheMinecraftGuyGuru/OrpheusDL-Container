#!/usr/bin/env python3
"""Simple web UI for managing OrpheusDL list files."""
from __future__ import annotations

import csv
import functools
import html
import imghdr
import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse, quote, unquote

import requests

LIST_LABELS: Dict[str, str] = {
    "artist": "Artists",
    "album": "Albums",
    "track": "Tracks",
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
      addSuccess: 'Album queued for luckysearch.',
      clearOnSuccess: true,
      buildQuery(values) {
        return joinNonEmpty([values['album-search-title'] || '', values['album-search-artist'] || '']);
      },
      buildSelectPayload(dataset) {
        const value = dataset.value || '';
        if (!value) {
          return null;
        }
        return {
          id: dataset.id || '',
          title: dataset.title || '',
          artist: dataset.artist || '',
          value,
          lookup: dataset.lookup || ''
        };
      },
      renderItem(item, escapeHtml) {
        const title = escapeHtml(item.title || '');
        const artist = escapeHtml(item.artist || '');
        const year = escapeHtml(item.year || '');
        const lookup = escapeHtml(item.lookup || '');
        const value = escapeHtml(item.value || '');
        const id = escapeHtml(item.id || '');
        const photo = typeof item.image === 'string' ? item.image.trim() : '';
        const safeImage = photo ? escapeHtml(photo) : '';
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
          '<button type="button" class="button success" data-select-type="album" data-id="' + id + '" data-title="' + title + '" data-artist="' + artist + '" data-value="' + value + '" data-lookup="' + lookup + '">Add</button>' +
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
      addSuccess: 'Track queued for luckysearch.',
      clearOnSuccess: true,
      buildQuery(values) {
        return joinNonEmpty([
          values['track-search-title'] || '',
          values['track-search-album'] || '',
          values['track-search-artist'] || ''
        ]);
      },
      buildSelectPayload(dataset) {
        const value = dataset.value || '';
        if (!value) {
          return null;
        }
        return {
          id: dataset.id || '',
          title: dataset.title || '',
          album: dataset.album || '',
          artist: dataset.artist || '',
          value,
          lookup: dataset.lookup || ''
        };
      },
      renderItem(item, escapeHtml) {
        const title = escapeHtml(item.title || '');
        const album = escapeHtml(item.album || '');
        const artist = escapeHtml(item.artist || '');
        const value = escapeHtml(item.value || '');
        const lookup = escapeHtml(item.lookup || '');
        const id = escapeHtml(item.id || '');
        const art = typeof item.image === 'string' ? item.image.trim() : '';
        const safeImage = art ? escapeHtml(art) : '';
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
          '<button type="button" class="button success" data-select-type="track" data-id="' + id + '" data-title="' + title + '" data-album="' + album + '" data-artist="' + artist + '" data-value="' + value + '" data-lookup="' + lookup + '">Add</button>' +
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

LISTS_DIR = Path(os.environ.get("LISTS_DIR", "/data/lists"))
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


def _list_path(kind: str) -> Path:
    if kind == "artist":
        return LISTS_DIR / "artists.csv"
    return LISTS_DIR / f"{kind}s.txt"


def _read_artist_entries_locked() -> List[Dict[str, str]]:
    path = _list_path("artist")
    if not path.exists():
        return []

    entries: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if not row:
                continue
            artist_id = row[0].strip()
            artist_name = row[1].strip() if len(row) > 1 else ""
            if not artist_id:
                continue
            entries.append({"id": artist_id, "name": artist_name})
    return entries


def _write_artist_entries_locked(entries: List[Dict[str, str]]) -> None:
    path = _list_path("artist")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for entry in entries:
            artist_id = str(entry.get("id", "")).strip()
            if not artist_id:
                continue
            writer.writerow([artist_id, str(entry.get("name", "")).strip()])


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


def _photo_file_path(identifier: str) -> Path:
    return PHOTOS_DIR / identifier


def _cached_artist_photo_url(artist_id: str) -> str:
    normalized = _normalize_photo_identifier(artist_id)
    if not normalized:
        return ""

    path = _photo_file_path(normalized)
    with _photo_lock:
        if path.exists() and path.is_file() and path.stat().st_size > 0:
            return f"/photos/{quote(normalized, safe='')}"
    return ""


def _ensure_artist_photo(artist_id: str, image_url: str | None) -> str:
    normalized = _normalize_photo_identifier(artist_id)
    if not normalized:
        return ""

    existing = _cached_artist_photo_url(normalized)
    if existing:
        return existing

    if not image_url:
        return ""

    try:
        response = requests.get(str(image_url), timeout=10)
        response.raise_for_status()
    except requests.RequestException as exc:
        logging.warning(
            "Failed to download artist photo for %s from %s: %s.",
            normalized,
            image_url,
            exc,
        )
        return ""

    data = response.content
    if not data:
        logging.debug("Artist photo response for %s was empty.", normalized)
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
                "Failed to store artist photo for %s: %s.",
                normalized,
                exc,
            )
            try:
                temp_path.unlink()
            except OSError:
                pass
            return ""

    logging.debug("Cached artist photo for %s at %s.", normalized, path)
    return f"/photos/{quote(normalized, safe='')}"


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
    kind = imghdr.what(None, data)
    if kind == "jpeg":
        return "image/jpeg"
    if kind == "png":
        return "image/png"
    if kind == "gif":
        return "image/gif"
    if kind == "bmp":
        return "image/bmp"
    if kind == "tiff":
        return "image/tiff"
    if kind == "webp":
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

        results.append(
            {
                "id": str(album_id),
                "title": title,
                "artist": artist_label,
                "year": year,
                "value": value,
                "lookup": lookup,
                "image": image_url,
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

        results.append(
            {
                "id": str(track_id),
                "title": title,
                "album": album_title,
                "artist": artist_name,
                "value": value,
                "lookup": lookup,
                "image": image_url,
            }
        )

    logging.info(
        "Qobuz track search for query %r returned %s result(s).",
        query,
        len(results),
    )
    return results


def ensure_lists_exist() -> None:
    LISTS_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        artist_path = _list_path("artist")
        if not artist_path.exists():
            legacy_path = LISTS_DIR / "artists.txt"
            if legacy_path.exists():
                legacy_entries: List[Dict[str, str]] = []
                for line in legacy_path.read_text(encoding="utf-8").splitlines():
                    artist_id = line.strip()
                    if not artist_id:
                        continue
                    legacy_entries.append({"id": artist_id, "name": artist_id})
                _write_artist_entries_locked(legacy_entries)
                logging.info(
                    "Migrated %s artist entries from legacy artists.txt to artists.csv.",
                    len(legacy_entries),
                )
                try:
                    legacy_path.unlink()
                except OSError:
                    logging.warning("Failed to remove legacy artists.txt file.")
            else:
                artist_path.parent.mkdir(parents=True, exist_ok=True)
                artist_path.touch(exist_ok=True)

        for kind in LIST_LABELS:
            if kind == "artist":
                continue
            _list_path(kind).touch(exist_ok=True)


def read_entries(kind: str) -> List[str] | List[Dict[str, str]]:
    if kind == "artist":
        with _lock:
            return _read_artist_entries_locked()

    path = _list_path(kind)
    if not path.exists():
        return []
    with _lock:
        lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip()]


def add_entry(
    kind: str,
    value: str,
    *,
    display_name: str | None = None,
) -> Tuple[bool, str]:
    value = value.strip()
    if not value:
        return False, "Value cannot be empty."

    if kind == "artist":
        artist_id = value
        artist_name = (display_name or "").strip() or artist_id
        with _lock:
            entries = _read_artist_entries_locked()
            if any(entry["id"] == artist_id for entry in entries):
                return False, f"{LIST_LABELS[kind][:-1]} already present."
            entries.append({"id": artist_id, "name": artist_name})
            _write_artist_entries_locked(entries)
        return True, f"Added {LIST_LABELS[kind][:-1]} '{artist_name}'."

    path = _list_path(kind)
    with _lock:
        entries = read_entries(kind)
        if value in entries:
            return False, f"{LIST_LABELS[kind][:-1]} already present."
        with path.open("a", encoding="utf-8") as handle:
            handle.write(value + "\n")
    return True, f"Added {LIST_LABELS[kind][:-1]} '{value}'."


def sanitize_entry_value(value: str) -> str | None:
    """Replicate the scheduler's trimming and comment filtering."""

    sanitized = value.strip()
    if not sanitized or sanitized.startswith("#"):
        return None
    return sanitized


def _enqueue_async_message(message: str, is_error: bool) -> None:
    with _async_lock:
        _async_messages.append((message, is_error))


def _consume_async_messages() -> List[Tuple[str, bool]]:
    with _async_lock:
        if not _async_messages:
            return []
        messages = list(_async_messages)
        _async_messages.clear()
        return messages


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

    worker = threading.Thread(
        target=_run_artist_download,
        args=(sanitized,),
        name="download-artist",
        daemon=True,
    )
    worker.start()


def _run_luckysearch(kind: str, value: str) -> None:
    command = [
        "python3",
        "-u",
        "orpheus.py",
        "luckysearch",
        "qobuz",
        kind,
        value,
    ]
    logging.info("Starting luckysearch for %s: %s", kind, value)
    try:
        result = subprocess.run(
            command,
            cwd="/orpheusdl",
            check=False,
        )
    except Exception as exc:  # pragma: no cover - subprocess failure
        logging.exception("Failed to launch luckysearch for %s: %s", kind, value)
        _enqueue_async_message(
            f"Luckysearch failed for {LIST_LABELS[kind][:-1]} '{value}': {exc}",
            True,
        )
        return

    if result.returncode != 0:
        logging.error(
            "Luckysearch exited with %s for %s:%s. See docker logs for output.",
            result.returncode,
            kind,
            value,
        )
        _enqueue_async_message(
            f"Luckysearch failed for {LIST_LABELS[kind][:-1]} '{value}': exit code {result.returncode}. Check logs for details.",
            True,
        )
    else:
        logging.info("Luckysearch succeeded for %s: %s", kind, value)


def _trigger_luckysearch(kind: str, value: str) -> None:
    sanitized = sanitize_entry_value(value)
    if sanitized is None:
        logging.info(
            "Skipping luckysearch for %s entry %r due to scheduler sanitisation.",
            kind,
            value,
        )
        if value.startswith("#"):
            _enqueue_async_message(
                f"Entry '{value}' added to {LIST_LABELS[kind]} but ignored because it starts with '#'.",
                False,
            )
        return

    worker = threading.Thread(
        target=_run_luckysearch,
        args=(kind, sanitized),
        name=f"luckysearch-{kind}",
        daemon=True,
    )
    worker.start()


def remove_entry(kind: str, index: int) -> Tuple[bool, str]:
    path = _list_path(kind)
    removed_label: str | None = None
    removed_artist_name: str | None = None
    with _lock:
        if kind == "artist":
            entries = _read_artist_entries_locked()
            if index < 0 or index >= len(entries):
                return False, "Entry not found."
            removed_entry = entries.pop(index)
            _write_artist_entries_locked(entries)
            removed_artist_name = (removed_entry.get("name") or "").strip()
            removed_label = (
                removed_artist_name
                or removed_entry.get("id")
                or ""
            )
        else:
            entries = read_entries(kind)
            if index < 0 or index >= len(entries):
                return False, "Entry not found."
            removed = entries.pop(index)
            data = "\n".join(entries)
            if data:
                data += "\n"
            path.write_text(data, encoding="utf-8")
            removed_label = removed
    if kind == "artist" and removed_artist_name:
        _delete_artist_directory(removed_artist_name)
    if removed_label is None:
        removed_label = ""
    return True, f"Removed {LIST_LABELS[kind][:-1]} '{removed_label}'."


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

        if parsed.path == "/purge-photos":
            self.handle_purge_photos(data)
            return

        if parsed.path == "/add":
            self.handle_add(data)
        elif parsed.path == "/delete":
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
                f"Added artist '{artist_name}' (ID {artist_id}) and started download."
            )
        else:
            combined_message = (
                f"Added artist ID {artist_id} and started download."
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
        lookup = data.get("lookup", "").strip()

        logging.info(
            "Received album selection from %s with id=%r title=%r artist=%r.",
            self.address_string(),
            album_id,
            album_title,
            album_artist,
        )

        if not stored_value:
            parts = [part for part in [album_artist, album_title] if part]
            if parts:
                stored_value = " - ".join(parts)
            elif album_id:
                stored_value = album_id

        if not stored_value:
            self.send_json(
                {"error": "Missing album details."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        success, add_message = add_entry("album", stored_value)

        if not success:
            self.send_json({"error": add_message}, status=HTTPStatus.CONFLICT)
            return

        logging.info("Album %s added to list: %s", stored_value, add_message)
        _trigger_luckysearch("album", (lookup or stored_value).strip())

        label = album_title or stored_value
        if album_artist and album_title:
            combined_message = (
                f"Added album '{album_title}' by {album_artist} and queued luckysearch."
            )
        elif album_artist:
            combined_message = (
                f"Added album by {album_artist} and queued luckysearch."
            )
        else:
            combined_message = f"Added album '{label}' and queued luckysearch."

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
        lookup = data.get("lookup", "").strip()

        logging.info(
            "Received track selection from %s with id=%r title=%r album=%r artist=%r.",
            self.address_string(),
            track_id,
            track_title,
            album_title,
            artist_name,
        )

        if not stored_value:
            parts = [part for part in [artist_name, track_title] if part]
            if parts:
                base_value = " - ".join(parts)
            else:
                base_value = ""
            if base_value and album_title:
                stored_value = f"{base_value} ({album_title})"
            elif base_value:
                stored_value = base_value
            elif album_title:
                stored_value = album_title
            elif track_id:
                stored_value = track_id

        if not stored_value:
            self.send_json(
                {"error": "Missing track details."},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        success, add_message = add_entry("track", stored_value)

        if not success:
            self.send_json({"error": add_message}, status=HTTPStatus.CONFLICT)
            return

        logging.info("Track %s added to list: %s", stored_value, add_message)
        _trigger_luckysearch("track", (lookup or stored_value).strip())

        label = track_title or stored_value
        pieces = [f"Added track '{label}'"]
        if artist_name:
            pieces.append(f"by {artist_name}")
        if album_title:
            pieces.append(f"from album '{album_title}'")
        combined_message = " ".join(pieces) + " and queued luckysearch."

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

    def handle_add(self, data: Dict[str, str]) -> None:
        kind = normalize_kind(data.get("list"))
        value = data.get("value", "").strip()
        label = data.get("label", "").strip()
        lookup = data.get("lookup", "").strip()
        selected = normalize_kind(data.get("selected"))
        if not kind:
            self.redirect_home("Unknown list type.", is_error=True)
            return
        if not selected:
            selected = kind
        if kind == "artist":
            success, message = add_entry(
                kind,
                value,
                display_name=label or value,
            )
        else:
            success, message = add_entry(kind, value)
        if success:
            if label and kind != "artist":
                message = f"Added {LIST_LABELS[kind][:-1]} '{label}'."
            if kind == "artist":
                _trigger_artist_download(value)
            else:
                _trigger_luckysearch(kind, (lookup or label or value).strip())
        self.redirect_home(message, is_error=not success, selected=selected)

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

                if kind == 'artist' and isinstance(entry, dict):
                    artist_id = (entry.get('id') or '').strip()
                    artist_name = (entry.get('name') or '').strip() or artist_id
                    primary = html.escape(artist_name or artist_id)
                    secondary_html = (
                        f'<span class="entry-secondary">ID: {html.escape(artist_id)}</span>'
                        if artist_id
                        else ''
                    )
                    row_items.append(
                        ''.join(
                            [
                                '<li class="entry">',
                                '<div class="entry-text">',
                                f'<span class="entry-primary">{primary}</span>',
                                secondary_html,
                                '</div>',
                                remove_form,
                                '</li>',
                            ]
                        )
                    )
                else:
                    entry_text = html.escape(str(entry))
                    row_items.append(
                        ''.join(
                            [
                                '<li class="entry">',
                                '<div class="entry-text">',
                                f'<span class="entry-primary">{entry_text}</span>',
                                '</div>',
                                remove_form,
                                '</li>',
                            ]
                        )
                    )

            rows_html = (
                '\n'.join(row_items)
                if row_items
                else '<li class=\"empty\">No entries yet.</li>'
            )

            placeholder = f'Add new {kind}'
            label_text = LIST_LABELS[kind][:-1]
            if kind == 'artist':
                label_text = 'Artist ID'
                placeholder = 'Add artist ID'
            elif kind == 'album':
                placeholder = 'Add new album'
            elif kind == 'track':
                placeholder = 'Add new track'

            add_form = ''.join(
                [
                    '<form method="post" action="/add" class="add-form">',
                    f'<input type="hidden" name="list" value="{kind}">',
                    f'<input type="hidden" name="selected" value="{kind}">',
                    '<div class="input-group">',
                    f'<span class="field-label">{html.escape(label_text)}</span>',
                    f'<input type="text" name="value" placeholder="{html.escape(placeholder)}" required>',
                    '</div>',
                    '<button type="submit" class="button primary">Add</button>',
                    '</form>',
                ]
            )

            active_class = ' active' if kind == normalized_selected else ''
            section_parts = [
                f'<section class="list-section{active_class}" data-list="{kind}">',
                '<div class="section-header">',
                f'<h2>{html.escape(label)}</h2>',
                '</div>',
                f'<ul class="entry-list">{rows_html}</ul>',
                add_form,
            ]

            if kind == 'artist':
                section_parts.append(ARTIST_SEARCH_SECTION)
            elif kind == 'album':
                section_parts.append(ALBUM_SEARCH_SECTION)
            elif kind == 'track':
                section_parts.append(TRACK_SEARCH_SECTION)

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
                '<form method="post" action="/purge-photos" class="inline-form purge-form">',
                f'<input type="hidden" name="selected" value="{escaped_selected}">',
                '<button type="submit" class="button warning">Purge Photos</button>',
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
                '.entry{display:flex;align-items:flex-start;justify-content:space-between;gap:0.75rem;padding:0.9rem 1rem;background:#0f1724;border:1px solid rgba(255,255,255,0.06);border-radius:10px;}',
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
                '.add-form{margin-top:1.25rem;display:flex;flex-wrap:wrap;gap:0.75rem;align-items:flex-end;}',
                '.input-group{display:flex;flex-direction:column;gap:0.35rem;width:100%;flex:1;}',
                '.field-label{font-size:0.85rem;color:#8d99bd;text-transform:uppercase;letter-spacing:0.05em;}',
                '.add-form input[type=text],.search-form input[type=search],.search-form input[type=text]{background:#0b1320;border:1px solid #2c3a55;border-radius:6px;padding:0.55rem 0.75rem;color:#f4f6ff;font-size:1rem;width:100%;}',
                '.add-form input[type=text]:focus,.search-form input[type=search]:focus,.search-form input[type=text]:focus{outline:2px solid #2f89fc;outline-offset:0;border-color:#2f89fc;}',
                '.search-block{margin-top:1.5rem;display:flex;flex-direction:column;gap:0.9rem;}',
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
                '@media (max-width:640px){.entry{flex-direction:column;align-items:stretch;}.inline-form{width:100%;}.inline-form .button{width:100%;}.add-form{flex-direction:column;align-items:stretch;}.add-form .button{width:100%;}.search-result{flex-direction:column;align-items:stretch;}.search-thumb{width:100%;height:auto;max-height:220px;}.search-thumb img{width:100%;height:auto;}.search-result .button{width:100%;}.search-actions{justify-content:stretch;}.search-actions .button{width:100%;}}',
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
