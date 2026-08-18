"""Application configuration and environment loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
COOKIE_DIR = BASE_DIR / "cookies"
CSV_PATH = DATA_DIR / "tweets.csv"
JSON_PATH = DATA_DIR / "tweets.json"
COOKIE_PATH = COOKIE_DIR / "cookies.json"

# Page requests are deliberately spaced out. Change these values if needed.
REQUEST_DELAY_MIN = 2.0
REQUEST_DELAY_MAX = 5.0
MAX_RETRIES = 3
RETRY_BASE_DELAY = 5.0
MAX_PAGES = 1_000
MAX_STALLED_PAGES = 3


@dataclass(frozen=True, slots=True)
class Credentials:
    username: str | None
    email: str | None
    password: str | None
    auth_token: str | None = None
    ct0: str | None = None

    @property
    def complete(self) -> bool:
        # Twikit 2.3.3 declares auth_info_2 as optional.
        return bool(self.username and self.password)

    @property
    def browser_cookies_complete(self) -> bool:
        return bool(self.auth_token and self.ct0)

    def missing_names(self) -> list[str]:
        required_values = {
            "X_USERNAME": self.username,
            "X_PASSWORD": self.password,
        }
        return [name for name, value in required_values.items() if not value]


def load_credentials() -> Credentials:
    """Load credentials from the project .env without logging their values."""
    load_dotenv(BASE_DIR / ".env")
    return Credentials(
        username=os.getenv("X_USERNAME") or None,
        email=os.getenv("X_EMAIL") or None,
        password=os.getenv("X_PASSWORD") or None,
        auth_token=os.getenv("X_AUTH_TOKEN") or None,
        ct0=os.getenv("X_CT0") or None,
    )


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    COOKIE_DIR.mkdir(parents=True, exist_ok=True)
