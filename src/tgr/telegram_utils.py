from __future__ import annotations

import html
import re
from typing import Iterable, Sequence

from telethon import types, utils

_REGEX_HINT_CHARS = set(r"\()[]{}|.+?^$*")


def escape(value: object) -> str:
    return html.escape(str(value))


def html_code(text: object) -> str:
    return f"<code>{escape(text)}</code>"


def resolve_peer_id(peer: object) -> int:
    try:
        raw_id = utils.get_peer_id(peer)
        if isinstance(peer, (types.PeerChannel, types.PeerChat)):
            raw = str(raw_id)
            if not raw.startswith("-100") and not raw.startswith("-"):
                return int(f"-100{raw}")
        return int(raw_id)
    except Exception:
        return 0


def dialog_filter_title(folder: types.DialogFilter) -> str:
    raw = folder.title
    return raw.text if hasattr(raw, "text") else str(raw)


def build_message_link(chat: object, chat_id: int, msg_id: int) -> str:
    username = getattr(chat, "username", None)
    if username:
        return f"https://t.me/{username}/{msg_id}"
    raw = str(abs(chat_id))
    if raw.startswith("100") and len(raw) >= 12:
        return f"https://t.me/c/{raw[3:]}/{msg_id}"
    return ""


def format_duration(seconds: float) -> str:
    total = int(seconds)
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if minutes:
        parts.append(f"{minutes}分")
    return " ".join(parts) or "不足1分钟"


def has_regex_hint(raw: str) -> bool:
    return any(ch in _REGEX_HINT_CHARS for ch in raw)


def _ensure_tokens(raw: str | Sequence[str]) -> list[str]:
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return []
        return [part.strip() for part in raw.split() if part.strip()]
    return [str(part).strip() for part in raw if str(part).strip()]


def normalize_pattern_from_terms(raw: str | Sequence[str]) -> str:
    tokens = _ensure_tokens(raw)
    if not tokens:
        raise ValueError("empty pattern")

    normalized: list[str] = []
    for token in tokens:
        normalized.append(token if has_regex_hint(token) else re.escape(token))

    if len(normalized) == 1:
        token = normalized[0]
        original = tokens[0]
        return token if has_regex_hint(original) else f"({token})"

    return "(" + "|".join(normalized) + ")"


def split_top_level_alternation(pattern: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    escaped = False
    depth_round = 0
    depth_square = 0
    depth_curly = 0

    for ch in pattern:
        if escaped:
            buf.append(ch)
            escaped = False
            continue

        if ch == "\\":
            buf.append(ch)
            escaped = True
            continue

        if ch == "(":
            depth_round += 1
        elif ch == ")":
            depth_round = max(0, depth_round - 1)
        elif ch == "[":
            depth_square += 1
        elif ch == "]":
            depth_square = max(0, depth_square - 1)
        elif ch == "{":
            depth_curly += 1
        elif ch == "}":
            depth_curly = max(0, depth_curly - 1)

        if ch == "|" and depth_round == 0 and depth_square == 0 and depth_curly == 0:
            part = "".join(buf).strip()
            if part:
                parts.append(part)
            buf = []
            continue

        buf.append(ch)

    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def try_remove_terms_from_pattern(pattern: str, terms: Iterable[str]) -> str | None:
    pattern = pattern.strip()
    if not pattern:
        return None

    inner = pattern[1:-1] if pattern.startswith("(") and pattern.endswith(")") else pattern
    tokens = split_top_level_alternation(inner)

    cleaned_terms = {t.strip() for t in terms if t.strip()}
    normalized_plain = {re.escape(t) for t in cleaned_terms if not has_regex_hint(t)}

    left: list[str] = []
    for token in tokens:
        token_plain = html.unescape(token)
        if token in cleaned_terms or token_plain in cleaned_terms:
            continue
        if token in normalized_plain or token_plain in normalized_plain:
            continue
        left.append(token)

    if not left:
        return None
    if len(left) == 1:
        only = left[0]
        return only if has_regex_hint(only) else f"({only})"
    return "(" + "|".join(left) + ")"


def truncate_for_panel(text: str, limit: int = 1200) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def compact_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def blockquote_preview(text: str, limit: int = 900) -> str:
    return f"<blockquote expandable>{escape(truncate_for_panel(compact_text(text), limit))}</blockquote>"


def bullet(label: str, value: object | None = None, *, code: bool = True, prefix: str = "·") -> str:
    if value is None:
        return f"{prefix} {escape(label)}"
    rendered = html_code(value) if code else escape(value)
    return f"{prefix} {escape(label)}：{rendered}"


def section(title: str, rows: Sequence[str]) -> str:
    rows = [row for row in rows if row]
    if not rows:
        return ""
    return f"<b>{escape(title)}</b>\n" + "\n".join(rows)


def panel(title: str, sections: Sequence[str], footer: str | None = None) -> str:
    body = [f"<b>{escape(title)}</b>"]
    for sec in sections:
        sec = sec.strip()
        if sec:
            body.append(sec)
    if footer:
        body.append(footer.strip())
    return "\n\n".join(body)


def shorten_path(path: object, keep: int = 2) -> str:
    parts = str(path).split("/")
    if len(parts) <= keep + 1:
        return str(path)
    return "…/" + "/".join(parts[-keep:])
