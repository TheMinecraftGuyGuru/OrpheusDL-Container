#!/usr/bin/env python3
"""Simple web UI for managing OrpheusDL list files."""
from __future__ import annotations

import functools
import html
import importlib.util
import json
import logging
import os
import subprocess
import sys
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

import requests

LIST_LABELS: Dict[str, str] = {
    "artist": "Artists",
    "album": "Albums",
    "track": "Tracks",
}

ARTIST_SEARCH_FORM = """
<div class=\"artist-search\">
  <h3>Search Qobuz</h3>
  <div class=\"search-controls\">
    <input type=\"search\" id=\"artist-search-input\" placeholder=\"Search Qobuz artists\" aria-label=\"Search Qobuz artists\">
    <button type=\"button\" id=\"artist-search-button\">Search</button>
  </div>
  <div id=\"artist-search-results\" class=\"search-results\">
    <div class=\"search-empty\">Use the search to add artists by Qobuz ID.</div>
  </div>
</div>
""".strip()

ARTIST_SEARCH_SCRIPT = """
<script>
(function() {
  const input = document.getElementById('artist-search-input');
  const button = document.getElementById('artist-search-button');
  const results = document.getElementById('artist-search-results');
  if (!input || !results) {
    return;
  }

  let activeController = null;
  const escapeMap = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': '&quot;', "'": "&#39;"};

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (char) => escapeMap[char] || char);
  }

  function showStatus(message) {
    results.innerHTML = '<div class="search-empty">' + escapeHtml(message) + '</div>';
  }

  function render(items) {
    if (!Array.isArray(items) || !items.length) {
      showStatus('No artists found.');
      return;
    }

    const markup = items.map((item) => {
      const image = item.image
        ? '<img src="' + escapeHtml(item.image) + '" alt="' + escapeHtml(item.name) + '" loading="lazy">'
        : '<div class="no-image" aria-hidden="true"></div>';
      return (
        '<div class="search-result">' +
        image +
        '<div class="search-meta">' +
        '<div class="search-name">' + escapeHtml(item.name) + '</div>' +
        '<div class="search-id">ID: ' + escapeHtml(item.id) + '</div>' +
        '<button type="button" class="search-add" data-artist-id="' + escapeHtml(item.id) + '" data-artist-name="' + escapeHtml(item.name) + '">Add</button>' +
        '</div></div>'
      );
    }).join('');

    results.innerHTML = markup;
  }

  async function runSearch() {
    const query = input.value.trim();
    if (!query) {
      showStatus('Enter a search term.');
      return;
    }

    if (activeController) {
      activeController.abort();
    }

    const controller = new AbortController();
    activeController = controller;
    showStatus('Searching…');

    try {
      const response = await fetch('/api/artist-search?q=' + encodeURIComponent(query), {signal: controller.signal});
      if (!response.ok) {
        let detail = 'HTTP ' + response.status;
        try {
          const data = await response.json();
          if (data && data.error) {
            detail = data.error;
          }
        } catch (_) {
          const text = await response.text();
          if (text) {
            detail = text;
          }
        }
        throw new Error(detail);
      }

      const data = await response.json();
      render(data.results || []);
    } catch (error) {
      if (error.name === 'AbortError') {
        return;
      }
      showStatus('Search failed: ' + error.message);
    } finally {
      if (activeController === controller) {
        activeController = null;
      }
    }
  }

  function submitArtist(id, name) {
    const form = document.createElement('form');
    form.method = 'post';
    form.action = '/add';

    const fields = {list: 'artist', value: 'qobuz:artist:' + id, label: name, lookup: name};
    Object.keys(fields).forEach((key) => {
      const field = document.createElement('input');
      field.type = 'hidden';
      field.name = key;
      field.value = fields[key];
      form.appendChild(field);
    });

    document.body.appendChild(form);
    form.submit();
  }

  if (button) {
    button.addEventListener('click', runSearch);
  }

  input.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      runSearch();
    }
  });

  results.addEventListener('click', (event) => {
    const buttonEl = event.target.closest('button[data-artist-id]');
    if (!buttonEl) {
      return;
    }
    submitArtist(buttonEl.getAttribute('data-artist-id'), buttonEl.getAttribute('data-artist-name') || '');
  });
})();
</script>
""".strip()

LISTS_DIR = Path(os.environ.get("LISTS_DIR", "/data/lists"))
WEB_HOST = os.environ.get("LISTS_WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("LISTS_WEB_PORT", "8080"))

BASE_DIR = Path(__file__).resolve().parent
_ORPHEUSDL_PATH = BASE_DIR / "external" / "orpheusdl"
if _ORPHEUSDL_PATH.exists():
    path_str = str(_ORPHEUSDL_PATH)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

_QOBUZ_MODULE_LOCK = threading.Lock()
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


def _list_path(kind: str) -> Path:
    return LISTS_DIR / f"{kind}s.txt"


def _load_qobuz_api_module():
    global _QOBUZ_API_MODULE
    with _QOBUZ_MODULE_LOCK:
        if _QOBUZ_API_MODULE is not None:
            return _QOBUZ_API_MODULE

        module_path = BASE_DIR / "external" / "orpheusdl-qobuz" / "qobuz_api.py"
        if not module_path.exists():
            raise RuntimeError("Qobuz integration is unavailable.")

        spec = importlib.util.spec_from_file_location(
            "orpheusdl_qobuz_api", module_path
        )
        if spec is None or spec.loader is None:
            raise RuntimeError("Unable to load Qobuz integration module.")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _QOBUZ_API_MODULE = module
        return module


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
    if not creds.get("app_id"):
        raise RuntimeError("Qobuz app_id is not configured.")
    return creds


def _get_qobuz_client():
    global _QOBUZ_CLIENT, _QOBUZ_CLIENT_CREDS
    creds = _collect_qobuz_credentials()

    with _QOBUZ_MODULE_LOCK:
        if _QOBUZ_CLIENT is not None and _QOBUZ_CLIENT_CREDS == creds:
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
        return session


def _qobuz_artist_search(query: str, limit: int = 10) -> List[Dict[str, str]]:
    if limit <= 0:
        limit = 10

    session = _get_qobuz_client()

    try:
        data = session.search("artist", query, limit=limit)
    except RuntimeError as exc:
        message = str(exc)
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            raise RuntimeError(message) from exc
        else:
            if isinstance(payload, dict):
                detail = payload.get("message") or payload.get("error") or payload.get("code")
                if detail:
                    raise RuntimeError(str(detail)) from exc
            raise RuntimeError(message) from exc
    except requests.exceptions.Timeout as exc:
        raise RuntimeError("Qobuz search timed out.") from exc
    except Exception as exc:  # pragma: no cover - network failure
        raise RuntimeError("Unable to reach Qobuz search endpoint.") from exc

    artists = data.get("artists", {}) or {}
    items = artists.get("items") or []
    results: List[Dict[str, str]] = []
    for item in items:
        artist_id = item.get("id")
        name = item.get("name") or item.get("title")
        if not artist_id or not name:
            continue

        images = item.get("image") or item.get("images") or {}
        image_url = (
            images.get("large")
            or images.get("extralarge")
            or images.get("medium")
            or images.get("small")
            or item.get("picture")
        )

        results.append(
            {
                "id": str(artist_id),
                "name": str(name),
                "image": str(image_url) if image_url else "",
            }
        )

    return results


def ensure_lists_exist() -> None:
    LISTS_DIR.mkdir(parents=True, exist_ok=True)
    with _lock:
        for kind in LIST_LABELS:
            _list_path(kind).touch(exist_ok=True)


def read_entries(kind: str) -> List[str]:
    path = _list_path(kind)
    if not path.exists():
        return []
    with _lock:
        lines = path.read_text(encoding="utf-8").splitlines()
    return [line.strip() for line in lines if line.strip()]


def add_entry(kind: str, value: str) -> Tuple[bool, str]:
    value = value.strip()
    if not value:
        return False, "Value cannot be empty."
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
            capture_output=True,
            text=True,
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
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        detail = stderr.splitlines()[-1] if stderr else stdout.splitlines()[-1] if stdout else "see logs"
        logging.error(
            "Luckysearch exited with %s for %s: %s", result.returncode, kind, value
        )
        _enqueue_async_message(
            f"Luckysearch failed for {LIST_LABELS[kind][:-1]} '{value}': {detail}",
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
    with _lock:
        entries = read_entries(kind)
        if index < 0 or index >= len(entries):
            return False, "Entry not found."
        removed = entries.pop(index)
        data = "\n".join(entries)
        if data:
            data += "\n"
        path.write_text(data, encoding="utf-8")
    return True, f"Removed {LIST_LABELS[kind][:-1]} '{removed}'."


def normalize_kind(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.lower().strip()
    if key.endswith("s"):
        key = key[:-1]
    return key if key in LIST_LABELS else None


def redirect_location(message: str | None = None, is_error: bool = False) -> str:
    if not message:
        return "/"
    payload = {"message": message}
    if is_error:
        payload["error"] = "1"
    return "/?" + urlencode(payload)


class ListRequestHandler(BaseHTTPRequestHandler):
    server_version = "OrpheusListHTTP/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/artist-search":
            self.handle_artist_search(parsed)
            return

        if parsed.path not in {"", "/"}:
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")
            return

        query = parse_qs(parsed.query)
        message = query.get("message", [None])[0]
        is_error = query.get("error", ["0"])[0] == "1"

        body = self.render_index(message=message, is_error=is_error)
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
        data = {k: v[0] for k, v in parse_qs(payload).items() if v}

        if parsed.path == "/add":
            self.handle_add(data)
        elif parsed.path == "/delete":
            self.handle_delete(data)
        else:
            self.send_error(HTTPStatus.NOT_FOUND, "Not Found")

    def handle_artist_search(self, parsed) -> None:
        params = parse_qs(parsed.query)
        query = (params.get("q") or [""])[0].strip()
        limit_raw = (params.get("limit") or ["10"])[0]
        try:
            limit = int(limit_raw)
        except ValueError:
            limit = 10

        if not query:
            self.send_json({"error": "Missing search query."}, status=HTTPStatus.BAD_REQUEST)
            return

        try:
            results = _qobuz_artist_search(query, limit=limit)
        except RuntimeError as exc:
            message = str(exc)
            status = HTTPStatus.SERVICE_UNAVAILABLE if "app_id" in message else HTTPStatus.BAD_GATEWAY
            logging.warning("Artist search failed: %s", message)
            self.send_json({"error": message}, status=status)
            return

        self.send_json({"results": results})

    def handle_add(self, data: Dict[str, str]) -> None:
        kind = normalize_kind(data.get("list"))
        value = data.get("value", "")
        label = data.get("label", "").strip()
        lookup = data.get("lookup", "").strip()
        if not kind:
            self.redirect_home("Unknown list type.", is_error=True)
            return
        success, message = add_entry(kind, value)
        if success:
            if label:
                message = f"Added {LIST_LABELS[kind][:-1]} '{label}'."
            _trigger_luckysearch(kind, (lookup or label or value).strip())
        self.redirect_home(message, is_error=not success)

    def handle_delete(self, data: Dict[str, str]) -> None:
        kind = normalize_kind(data.get("list"))
        if not kind:
            self.redirect_home("Unknown list type.", is_error=True)
            return
        try:
            index = int(data.get("index", ""))
        except ValueError:
            self.redirect_home("Invalid entry index.", is_error=True)
            return
        success, message = remove_entry(kind, index)
        self.redirect_home(message, is_error=not success)

    def redirect_home(self, message: str | None, is_error: bool = False) -> None:
        location = redirect_location(message=message, is_error=is_error)
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def render_index(self, message: str | None, is_error: bool) -> str:
        sections = []
        for kind, label in LIST_LABELS.items():
            entries = read_entries(kind)
            row_items = []
            for idx, entry in enumerate(entries):
                row_items.append(
                    f"<li><span>{html.escape(entry)}</span> "
                    f"<form method=\"post\" action=\"/delete\" class=\"inline\">"
                    f"<input type=\"hidden\" name=\"list\" value=\"{kind}\">"
                    f"<input type=\"hidden\" name=\"index\" value=\"{idx}\">"
                    f"<button type=\"submit\" class=\"delete\">Remove</button>"
                    f"</form></li>"
                )
            rows_html = "\n".join(row_items) or "<li class=\"empty\">No entries yet.</li>"
            placeholder = f"Add new {kind}"
            if kind == "artist":
                placeholder = "Add artist ID"

            section_parts = [
                "<section>",
                f"<h2>{html.escape(label)}</h2>",
                f"<ul>\n{rows_html}\n</ul>",
                f"<form method=\"post\" action=\"/add\" class=\"add-form\">",
                f"<input type=\"hidden\" name=\"list\" value=\"{kind}\">",
                f"<input type=\"text\" name=\"value\" placeholder=\"{html.escape(placeholder)}\" required>",
                f"<button type=\"submit\">Add</button>",
                "</form>",
            ]
            if kind == "artist":
                section_parts.append(ARTIST_SEARCH_FORM)
            section_parts.append("</section>")
            sections.append("".join(section_parts))

        banners: List[Tuple[str, bool]] = []
        if message:
            banners.append((message, is_error))
        banners.extend(_consume_async_messages())

        message_html = "".join(
            f"<div class=\"banner {'error' if banner_is_error else 'info'}\">{html.escape(banner_message)}</div>"
            for banner_message, banner_is_error in banners
        )

        return (
            "<!DOCTYPE html>"
            "<html lang=\"en\">"
            "<head>"
            "<meta charset=\"utf-8\">"
            "<title>OrpheusDL Lists</title>"
            "<style>"
            "body{font-family:Arial,Helvetica,sans-serif;background:#101820;color:#f2f2f2;margin:0;padding:2rem;}"
            "h1{margin-top:0;}section{background:#1f2a3a;border-radius:8px;padding:1.5rem;margin-bottom:1.5rem;}"
            "h2{margin-top:0;}ul{list-style:none;padding:0;}li{display:flex;align-items:center;justify-content:space-between;padding:0.35rem 0;border-bottom:1px solid rgba(255,255,255,0.08);}"
            "li:last-child{border-bottom:none;}li span{flex:1;}form.inline{display:inline;}"
            "button{background:#2f89fc;color:#fff;border:none;padding:0.4rem 0.8rem;border-radius:4px;cursor:pointer;}"
            "button.delete{background:#d9534f;}button:hover{opacity:0.85;}"
            ".add-form{margin-top:1rem;display:flex;gap:0.5rem;}"
            ".add-form input[type=text]{flex:1;padding:0.45rem;border-radius:4px;border:1px solid #3c4b63;background:#0d141f;color:#f2f2f2;}"
            ".banner{margin-bottom:1rem;padding:0.75rem 1rem;border-radius:6px;}"
            ".banner.info{background:#2f89fc33;border:1px solid #2f89fc;}"
            ".banner.error{background:#d9534f33;border:1px solid #d9534f;}"
            ".empty{color:#a3adcb;font-style:italic;}"
            ".artist-search{margin-top:1.5rem;}"
            ".artist-search h3{margin:0 0 0.75rem;font-size:1.1rem;}"
            ".search-controls{display:flex;gap:0.5rem;align-items:center;margin-bottom:0.75rem;}"
            ".search-controls input[type=search]{flex:1;padding:0.45rem;border-radius:4px;border:1px solid #3c4b63;background:#0d141f;color:#f2f2f2;}"
            ".search-controls button{background:#1bbf72;}"
            ".search-results{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:0.75rem;}"
            ".search-result{display:flex;gap:0.75rem;background:#152030;border-radius:6px;padding:0.75rem;align-items:center;}"
            ".search-result img,.search-result .no-image{width:64px;height:64px;border-radius:50%;object-fit:cover;background:#0d141f;}"
            ".search-result .no-image{display:flex;align-items:center;justify-content:center;color:#6c7898;font-size:0.75rem;}"
            ".search-meta{flex:1;display:flex;flex-direction:column;gap:0.35rem;}"
            ".search-add{align-self:flex-start;background:#1bbf72;}"
            ".search-id{font-size:0.8rem;color:#a3adcb;}"
            ".search-empty{color:#a3adcb;font-style:italic;}"
            "</style>"
            "</head>"
            "<body>"
            "<h1>OrpheusDL Lists</h1>"
            f"{message_html}"
            f"{''.join(sections)}"
            f"{ARTIST_SEARCH_SCRIPT}"
            "</body>"
            "</html>"
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
