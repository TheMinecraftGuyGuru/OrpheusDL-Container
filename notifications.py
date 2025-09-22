#!/usr/bin/env python3
"""Utility helpers for sending Discord webhook notifications."""
from __future__ import annotations

import argparse
import logging
import os
from typing import Any, Mapping, MutableMapping, Optional

import requests

_LOGGER = logging.getLogger(__name__)


def _get_webhook_url() -> Optional[str]:
    """Return the configured Discord webhook URL if one is set."""

    return os.environ.get("DISCORD_WEBHOOK_URL") or os.environ.get("DISCORD_WEBHOOK")


def send_discord_notification(
    message: str,
    *,
    title: str | None = None,
    level: str = "info",
    event: str | None = None,
    details: Mapping[str, str] | None = None,
    username: str | None = None,
    timeout: float = 10.0,
) -> bool:
    """Send a structured Discord webhook message.

    The function is intentionally forgiving: if the webhook URL is not configured or the
    HTTP request fails, the exception is swallowed and ``False`` is returned so callers
    can treat notifications as best-effort signals rather than hard requirements.
    """

    webhook_url = _get_webhook_url()
    if not webhook_url:
        _LOGGER.debug(
            "Discord webhook not configured; skipping event %s with message %r.",
            event or "<unspecified>",
            message,
        )
        return False

    safe_level = (level or "info").lower().strip()
    colour_map = {
        "debug": 0x95A5A6,
        "info": 0x3498DB,
        "success": 0x2ECC71,
        "warning": 0xF1C40F,
        "error": 0xE74C3C,
        "critical": 0xC0392B,
    }
    colour = colour_map.get(safe_level, colour_map["info"])

    embed: MutableMapping[str, Any] = {"description": message, "color": colour}
    if title:
        embed["title"] = title
    if event:
        embed.setdefault("footer", {})
        embed["footer"]["text"] = f"Event: {event}"

    if details:
        fields = []
        for key, value in details.items():
            if not key:
                continue
            fields.append({"name": str(key), "value": str(value) or "—", "inline": False})
        if fields:
            embed["fields"] = fields

    payload: MutableMapping[str, Any] = {"embeds": [embed]}
    if username:
        payload["username"] = username

    try:
        response = requests.post(webhook_url, json=payload, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:  # pragma: no cover - network failure
        _LOGGER.warning(
            "Failed to send Discord notification for event %s: %s",
            event or "<unspecified>",
            exc,
        )
        return False

    return True


def _parse_detail(detail: str) -> tuple[str, str | None]:
    key, _, value = detail.partition("=")
    return key.strip(), value.strip() if value else None


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Send a Discord webhook notification")
    parser.add_argument("--message", required=True, help="Notification message body")
    parser.add_argument("--title", help="Optional embed title")
    parser.add_argument("--event", help="Event identifier included in the footer")
    parser.add_argument(
        "--level",
        default="info",
        help="Severity level (info, warning, error, etc.) used to colour the embed",
    )
    parser.add_argument(
        "--detail",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Extra field to attach to the embed (repeatable)",
    )
    parser.add_argument(
        "--username",
        help="Override the webhook username. Defaults to Discord configuration.",
    )
    args = parser.parse_args(argv)

    detail_map: dict[str, str] = {}
    for raw_detail in args.detail:
        key, value = _parse_detail(raw_detail)
        if not key:
            continue
        detail_map[key] = value or ""

    success = send_discord_notification(
        args.message,
        title=args.title,
        level=args.level,
        event=args.event,
        details=detail_map or None,
        username=args.username,
    )
    return 0 if success else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(_main())
