#!/usr/bin/env python3
"""Simple web UI for managing OrpheusDL list files."""
from __future__ import annotations

import html
import logging
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import parse_qs, urlencode, urlparse

LIST_LABELS: Dict[str, str] = {
    "artist": "Artists",
    "album": "Albums",
    "track": "Tracks",
}

LISTS_DIR = Path(os.environ.get("LISTS_DIR", "/data/lists"))
WEB_HOST = os.environ.get("LISTS_WEB_HOST", "0.0.0.0")
WEB_PORT = int(os.environ.get("LISTS_WEB_PORT", "8080"))

_lock = threading.RLock()


def _list_path(kind: str) -> Path:
    return LISTS_DIR / f"{kind}s.txt"


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

    def handle_add(self, data: Dict[str, str]) -> None:
        kind = normalize_kind(data.get("list"))
        value = data.get("value", "")
        if not kind:
            self.redirect_home("Unknown list type.", is_error=True)
            return
        success, message = add_entry(kind, value)
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
            sections.append(
                f"<section>"
                f"<h2>{html.escape(label)}</h2>"
                f"<ul>\n{rows_html}\n</ul>"
                f"<form method=\"post\" action=\"/add\" class=\"add-form\">"
                f"<input type=\"hidden\" name=\"list\" value=\"{kind}\">"
                f"<input type=\"text\" name=\"value\" placeholder=\"Add new {kind}\" required>"
                f"<button type=\"submit\">Add</button>"
                f"</form>"
                f"</section>"
            )

        message_html = ""
        if message:
            cls = "error" if is_error else "info"
            message_html = f"<div class=\"banner {cls}\">{html.escape(message)}</div>"

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
            "</style>"
            "</head>"
            "<body>"
            "<h1>OrpheusDL Lists</h1>"
            f"{message_html}"
            f"{''.join(sections)}"
            "</body>"
            "</html>"
        )

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
