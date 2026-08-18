"""Data normalization, safe error formatting, and result persistence."""

from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


CSV_FIELDS = [
    "keyword",
    "tweet_id",
    "url",
    "display_name",
    "username",
    "user_id",
    "text",
    "created_at",
    "favorite_count",
    "retweet_count",
    "reply_count",
    "view_count",
    "collected_at",
]


def safe_getattr(obj: Any, name: str, default: Any = None) -> Any:
    """Read third-party model fields whose properties may raise on missing data."""
    if obj is None:
        return default
    try:
        return getattr(obj, name, default)
    except (AttributeError, KeyError, TypeError, ValueError):
        return default


def to_serializable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def normalize_tweet(tweet: Any, keyword: str) -> dict[str, Any]:
    """Convert a Twikit Tweet into a stable, version-tolerant record."""
    user = safe_getattr(tweet, "user")
    tweet_id = to_serializable(safe_getattr(tweet, "id"))
    username = to_serializable(safe_getattr(user, "screen_name"))
    url = (
        f"https://x.com/{username}/status/{tweet_id}"
        if username and tweet_id
        else None
    )

    # full_text includes long-form note tweets in Twikit 2.3.3.
    text = safe_getattr(tweet, "full_text")
    if text is None:
        text = safe_getattr(tweet, "text")

    return {
        "keyword": keyword,
        "tweet_id": tweet_id,
        "url": url,
        "display_name": to_serializable(safe_getattr(user, "name")),
        "username": username,
        "user_id": to_serializable(safe_getattr(user, "id")),
        "text": to_serializable(text),
        "created_at": to_serializable(safe_getattr(tweet, "created_at")),
        "favorite_count": to_serializable(safe_getattr(tweet, "favorite_count")),
        "retweet_count": to_serializable(safe_getattr(tweet, "retweet_count")),
        "reply_count": to_serializable(safe_getattr(tweet, "reply_count")),
        "view_count": to_serializable(safe_getattr(tweet, "view_count")),
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }


def redact_error(error: BaseException, secrets: Iterable[str | None]) -> str:
    """Return an exception message with known credentials removed."""
    message = f"{type(error).__name__}: {error}"
    for secret in secrets:
        if secret:
            message = message.replace(secret, "***")
    message = message.replace("\r", " ").replace("\n", " ")
    message = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "***.***.***.***", message)
    if "<!DOCTYPE html" in message or "<html" in message.lower():
        status_match = re.search(r"status:\s*(\d{3})", message, re.IGNORECASE)
        status = f"HTTP {status_match.group(1)}" if status_match else "HTTP 오류"
        return f"{type(error).__name__}: {status} (HTML 응답 본문은 보안상 생략)"
    if len(message) > 1_000:
        return message[:1_000] + "... (이하 생략)"
    return message


def save_results(
    records: Iterable[Mapping[str, Any]], csv_path: Path, json_path: Path
) -> None:
    """Atomically replace both output files with the currently collected data."""
    rows = [{field: to_serializable(row.get(field)) for field in CSV_FIELDS} for row in records]
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_tmp = csv_path.with_suffix(csv_path.suffix + ".tmp")
    json_tmp = json_path.with_suffix(json_path.suffix + ".tmp")

    try:
        with csv_tmp.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
        csv_tmp.replace(csv_path)

        with json_tmp.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(rows, file, ensure_ascii=False, indent=2)
            file.write("\n")
        json_tmp.replace(json_path)
    finally:
        csv_tmp.unlink(missing_ok=True)
        json_tmp.unlink(missing_ok=True)
