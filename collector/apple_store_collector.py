from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

import requests


SOURCE_KEY = "apple_app_store"
SOURCE_NAME = "Apple App Store"
APPLE_LOOKUP_URL = "https://itunes.apple.com/lookup"
APPLE_REVIEW_FEED_URL = (
    "https://itunes.apple.com/{country}/rss/customerreviews/"
    "page={page}/sortBy=mostRecent/id={app_id}/json"
)
USER_AGENT = "Sciencia Apple Review Pipeline/1.0"


class AppleStoreCollectorError(RuntimeError):
    """Raised when the Apple review collector cannot fetch or parse a feed."""


@dataclass(frozen=True)
class AppleReview:
    source: str
    app_id: str
    app_name: str
    country: str
    review_id: str
    author: str | None
    rating: int
    version: str | None
    title: str | None
    review_text: str
    review_date: str
    collected_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def review_feed_url(app_id: str, country: str, page: int) -> str:
    return APPLE_REVIEW_FEED_URL.format(
        country=country.lower(),
        page=page,
        app_id=app_id,
    )


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "User-Agent": USER_AGENT})
    return session


def _label(entry: dict[str, Any], *path: str, strip: bool = True) -> str | None:
    value: Any = entry
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)

    if not isinstance(value, str):
        return None
    return value.strip() if strip else value


def _request_json(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    timeout: int = 25,
    retries: int = 3,
    backoff_seconds: float = 1.0,
) -> dict[str, Any] | None:
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            response = session.get(url, params=params, timeout=timeout)
            if response.status_code == 404:
                return None
            if response.status_code in {429, 500, 502, 503, 504} and attempt < retries:
                time.sleep(backoff_seconds * (2**attempt))
                continue

            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise AppleStoreCollectorError("Apple response JSON was not an object.")
            return data
        except (requests.RequestException, ValueError, AppleStoreCollectorError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(backoff_seconds * (2**attempt))

    raise AppleStoreCollectorError(
        f"Apple request failed after {retries + 1} attempts: {last_error}"
    )


def resolve_app_name(
    app_id: str,
    country: str = "us",
    *,
    session: requests.Session | None = None,
    retries: int = 3,
) -> str:
    owns_session = session is None
    active_session = session or _session()
    try:
        data = _request_json(
            active_session,
            APPLE_LOOKUP_URL,
            params={"id": app_id, "country": country.lower()},
            retries=retries,
        )
    finally:
        if owns_session:
            active_session.close()

    if not data:
        return f"App {app_id}"

    results = data.get("results", [])
    if not isinstance(results, list) or not results:
        return f"App {app_id}"

    track_name = results[0].get("trackName")
    return str(track_name).strip() if track_name else f"App {app_id}"


def fetch_review_page(
    app_id: str,
    country: str,
    page: int,
    *,
    session: requests.Session | None = None,
    retries: int = 3,
) -> list[dict[str, Any]]:
    owns_session = session is None
    active_session = session or _session()
    try:
        data = _request_json(
            active_session,
            review_feed_url(app_id=app_id, country=country, page=page),
            retries=retries,
        )
    finally:
        if owns_session:
            active_session.close()

    if data is None:
        return []

    entries = data.get("feed", {}).get("entry", [])
    if isinstance(entries, dict):
        entries = [entries]
    if not isinstance(entries, list):
        raise AppleStoreCollectorError("Apple review feed entry field was malformed.")

    return [entry for entry in entries if isinstance(entry, dict)]


def parse_review_entry(
    entry: dict[str, Any],
    *,
    app_id: str,
    app_name: str,
    country: str,
    collected_at: str,
) -> AppleReview | None:
    review_id = _label(entry, "id", "label")
    raw_rating = _label(entry, "im:rating", "label")
    review_text = _label(entry, "content", "label", strip=False)
    review_date = _label(entry, "updated", "label")

    if not review_id or not raw_rating or review_text is None or not review_date:
        return None

    try:
        rating = int(raw_rating)
    except ValueError:
        return None

    if rating < 1 or rating > 5:
        return None

    return AppleReview(
        source=SOURCE_KEY,
        app_id=str(app_id),
        app_name=app_name,
        country=country.lower(),
        review_id=review_id,
        author=_label(entry, "author", "name", "label"),
        rating=rating,
        version=_label(entry, "im:version", "label"),
        title=_label(entry, "title", "label"),
        review_text=review_text,
        review_date=review_date,
        collected_at=collected_at,
    )


def collect_apple_reviews(
    app_id: str,
    country: str,
    pages: int,
    *,
    app_name: str | None = None,
    session: requests.Session | None = None,
    retries: int = 3,
    delay_seconds: float = 0.25,
) -> list[dict[str, Any]]:
    if pages < 1:
        raise ValueError("pages must be at least 1")

    country_code = country.lower().strip()
    if not country_code:
        raise ValueError("country must not be empty")

    owns_session = session is None
    active_session = session or _session()
    collected_at = utc_now()
    parsed_reviews: list[AppleReview] = []
    seen_review_ids: set[str] = set()

    try:
        resolved_name = app_name or resolve_app_name(
            app_id,
            country_code,
            session=active_session,
            retries=retries,
        )

        for page in range(1, pages + 1):
            entries = fetch_review_page(
                app_id,
                country_code,
                page,
                session=active_session,
                retries=retries,
            )
            if not entries:
                break

            for entry in entries:
                review = parse_review_entry(
                    entry,
                    app_id=app_id,
                    app_name=resolved_name,
                    country=country_code,
                    collected_at=collected_at,
                )
                if review is None or review.review_id in seen_review_ids:
                    continue
                seen_review_ids.add(review.review_id)
                parsed_reviews.append(review)

            if delay_seconds > 0 and page < pages:
                time.sleep(delay_seconds)
    finally:
        if owns_session:
            active_session.close()

    return [review.to_dict() for review in parsed_reviews]


def collect_many(
    requests_to_collect: Iterable[tuple[str, str, int]],
    *,
    retries: int = 3,
    delay_seconds: float = 0.25,
) -> list[dict[str, Any]]:
    reviews: list[dict[str, Any]] = []
    with _session() as session:
        for app_id, country, pages in requests_to_collect:
            reviews.extend(
                collect_apple_reviews(
                    app_id=app_id,
                    country=country,
                    pages=pages,
                    session=session,
                    retries=retries,
                    delay_seconds=delay_seconds,
                )
            )
    return reviews

