"""Telegram delivery + notification settings persistence (Plan 6 M1).

Free, no-VPS notification channel: a plain HTTPS POST to the Telegram Bot API.
The credentials file is never returned in full over HTTP — every read is
masked (``configured`` + last 4 chars of the token) so the token can't leak
through a browser devtools tab or a screen share.

**S18 (codex audit) — the token still sits in ``data/config/notifications.json``
as plain text.** That is a real gap the HTTP-layer masking above does nothing
for: anyone with filesystem access (a backup tool, a screen share of a file
browser, OneDrive's own cloud copy/version history) can read it directly.
There is no secrets manager available on this single-user localhost box, so
the realistic hardening is (a) restrict the file's permissions to the current
user only — best-effort, see ``_restrict_to_owner`` — and (b) recommend the
user rotate the token via @BotFather's ``/revoke`` if it may already have
been exposed (this file predates the restriction below). Neither makes the
token un-readable to someone with access to THIS machine's own user account —
that was never the threat model; it only narrows "readable by this file" to
"readable by whoever can already read this user's files".
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import requests

CONFIG_PATH = Path("data/config/notifications.json")
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
REQUEST_TIMEOUT_S = 10


def _restrict_to_owner(path: Path) -> None:
    """Best-effort file-permission hardening — never raises, since a
    credentials file failing to save because permission-locking failed would
    be strictly worse than an unrestricted-but-saved one.

    POSIX: chmod 600 (owner read/write only) via Python's own os.chmod, which
    actually enforces ACLs there. Windows: os.chmod only toggles the DOS
    read-only attribute (no real ACL effect), so this also shells out to
    ``icacls`` to strip inherited permissions and grant only the current
    user — the standard way to restrict a single file's ACL from the command
    line without the pywin32 dependency this project doesn't otherwise need.
    """
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    if os.name == "nt":
        try:
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{os.environ.get('USERNAME', '')}:F"],
                capture_output=True, timeout=5, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            pass


def _read_config(path: Path | None = None) -> dict[str, Any]:
    p = path or CONFIG_PATH
    if not p.exists():
        return {"telegram_bot_token": "", "telegram_chat_id": "", "enabled": False}
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"telegram_bot_token": "", "telegram_chat_id": "", "enabled": False}


def save_config(telegram_bot_token: str, telegram_chat_id: str, enabled: bool,
                 path: Path | None = None) -> None:
    p = path or CONFIG_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({
            "telegram_bot_token": telegram_bot_token,
            "telegram_chat_id": telegram_chat_id,
            "enabled": enabled,
        }, f, indent=2)
    _restrict_to_owner(tmp)  # lock down before the rename, never a moment unrestricted
    tmp.replace(p)
    _restrict_to_owner(p)  # os.replace can reset attributes on some platforms; re-assert


def masked_config(path: Path | None = None) -> dict[str, Any]:
    """Never exposes the real token — only whether one is configured and its
    last 4 characters, enough for the user to recognize which bot is saved."""
    cfg = _read_config(path)
    token = cfg.get("telegram_bot_token") or ""
    chat_id = cfg.get("telegram_chat_id") or ""
    return {
        "configured": bool(token) and bool(chat_id),
        "enabled": bool(cfg.get("enabled")),
        "token_last4": token[-4:] if len(token) >= 4 else "",
        "chat_id": chat_id,  # a chat id is not a secret the way a bot token is
    }


def send_telegram_message(text: str, path: Path | None = None) -> dict[str, Any]:
    """Send ``text`` via the configured Telegram bot. Never raises — returns
    ``{"ok": bool, "error": str | None}`` so both the test-button endpoint and
    the alert scanner's notifier can handle failure the same uniform way."""
    cfg = _read_config(path)
    token = cfg.get("telegram_bot_token")
    chat_id = cfg.get("telegram_chat_id")
    if not token or not chat_id:
        return {"ok": False, "error": "Telegram is not configured (missing bot token or chat id)."}
    try:
        resp = requests.post(
            TELEGRAM_API.format(token=token),
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=REQUEST_TIMEOUT_S,
        )
        data = resp.json()
        if not data.get("ok"):
            return {"ok": False, "error": data.get("description", f"Telegram API error (HTTP {resp.status_code}).")}
        return {"ok": True, "error": None}
    except requests.RequestException as e:
        return {"ok": False, "error": f"Network error contacting Telegram: {e}"}
    except Exception as e:  # never let a malformed response raise into the caller
        return {"ok": False, "error": f"Unexpected error: {e}"}


def is_enabled(path: Path | None = None) -> bool:
    cfg = _read_config(path)
    return bool(cfg.get("enabled")) and bool(cfg.get("telegram_bot_token")) and bool(cfg.get("telegram_chat_id"))


def telegram_notifier(payload: dict[str, Any]) -> None:
    """Plan 6 M4's Notifier — formats an alert payload and sends it. Wired as
    the alert scheduler's notifier factory once the user enables notifications."""
    from backend.alert_messages import format_alert_message
    result = send_telegram_message(format_alert_message(payload))
    if not result["ok"]:
        print(f"[notify] Telegram delivery failed (non-fatal): {result['error']}")


def telegram_pdt_notifier(payload: dict[str, Any]) -> None:
    """S23 — the PDT scanner's Notifier. Same delivery path as
    ``telegram_notifier``, different message template (no fixed rule/RR to
    quote — every new Mother Bar alerts, carrying whatever TP% it computed)."""
    from backend.alert_messages import format_pdt_message
    result = send_telegram_message(format_pdt_message(payload))
    if not result["ok"]:
        print(f"[notify] Telegram PDT delivery failed (non-fatal): {result['error']}")
