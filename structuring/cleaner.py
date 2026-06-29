from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Any

from dateutil import parser as date_parser


WHITESPACE_RE = re.compile(r"\s+")


def clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = html.unescape(str(value))
    text = WHITESPACE_RE.sub(" ", text).strip()
    return text or None


def clean_rating(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        rating = int(float(str(value).strip()))
    except ValueError:
        return None
    if 1 <= rating <= 5:
        return rating
    return None


def clean_datetime(value: Any) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = date_parser.parse(str(value))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
