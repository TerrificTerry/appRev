from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parent


def load_environment(path: Path) -> None:
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
    else:
        load_dotenv(path)


load_environment(BASE_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    source: str = os.getenv("SOURCE", "books")
    base_url: str = os.getenv("BASE_URL", "https://books.toscrape.com/")
    max_pages: int = int(os.getenv("MAX_PAGES", "3"))
    request_timeout: int = int(os.getenv("REQUEST_TIMEOUT", "15"))
    request_delay_seconds: float = float(os.getenv("REQUEST_DELAY_SECONDS", "1.0"))
    user_agent: str = os.getenv(
        "USER_AGENT",
        "ScienciaDataIngestionBot/0.1 (+local educational project)",
    )
    database_url: str = os.getenv(
        "DATABASE_URL",
        f"sqlite:///{(BASE_DIR / 'data' / 'reviews.db').as_posix()}",
    )
    raw_dir: Path = BASE_DIR / os.getenv("RAW_DIR", "data/raw")
    processed_dir: Path = BASE_DIR / os.getenv("PROCESSED_DIR", "data/processed")
    log_dir: Path = BASE_DIR / os.getenv("LOG_DIR", "logs")


settings = Settings()
