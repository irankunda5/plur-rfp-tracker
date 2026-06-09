"""Base scraper ABC with retry, rate limiting, and logging."""

import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SYSTEM_CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_BACKOFF = 2.0   # seconds; doubles each attempt
DEFAULT_DELAY = 1.5          # minimum seconds between requests
DEFAULT_TIMEOUT = 20.0


class BaseScraper(ABC):
    """Abstract base for RFP portal scrapers.

    Subclasses implement scrape() and return a list of classified opportunities.
    Retry logic, rate limiting, and logging are handled here.
    """

    #: Human-readable name used in logging and Opportunity.source
    name: str = "base"

    #: Landing / entry URL for this portal
    url: str = ""

    def __init__(
        self,
        config: dict | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        delay_seconds: float = DEFAULT_DELAY,
        timeout: float = DEFAULT_TIMEOUT,
        base_backoff: float = DEFAULT_BASE_BACKOFF,
    ):
        self._config = config or {}
        self._max_retries = max_retries
        self._delay_seconds = delay_seconds
        self._timeout = timeout
        self._base_backoff = base_backoff
        self._last_run: Optional[datetime] = None
        self._last_request_time: float = 0.0

        # Build httpx client (sync - procurement portals don't need async fan-out)
        import ssl
        ssl_ctx = ssl.create_default_context(cafile=SYSTEM_CA_BUNDLE)
        self._client = httpx.Client(
            timeout=httpx.Timeout(self._timeout),
            headers={"User-Agent": "rfp-tracker/1.0"},
            verify=ssl_ctx,
            follow_redirects=True,
        )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if not self._client.is_closed:
            self._client.close()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def last_run(self) -> Optional[datetime]:
        """UTC datetime of the last successful scrape(), or None."""
        return self._last_run

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _wait_for_rate_limit(self) -> None:
        """Block until the minimum delay since the last request has elapsed."""
        if self._delay_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self._delay_seconds:
            time.sleep(self._delay_seconds - elapsed)

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Rate-limited HTTP request with retry on transient errors.

        Args:
            method: HTTP method ("GET" or "POST").
            url: Target URL.
            **kwargs: Passed through to httpx.Client.request().

        Raises:
            httpx.HTTPError on non-retryable failures or exhausted retries.
        """
        self._wait_for_rate_limit()
        last_exc: Optional[Exception] = None
        last_response: Optional[httpx.Response] = None

        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.request(method, url, **kwargs)
                self._last_request_time = time.monotonic()

                if resp.status_code not in RETRYABLE_STATUSES:
                    resp.raise_for_status()
                    return resp

                last_response = resp
                logger.warning(
                    "[%s] HTTP %d on %s attempt %d/%d: %s",
                    self.name, resp.status_code, method,
                    attempt + 1, self._max_retries + 1, url,
                )

            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                logger.warning(
                    "[%s] Network error on %s attempt %d/%d: %s",
                    self.name, method, attempt + 1, self._max_retries + 1, exc,
                )

            if attempt < self._max_retries:
                backoff = self._base_backoff * (2 ** attempt)
                logger.debug("[%s] Backing off %.1fs before retry", self.name, backoff)
                time.sleep(backoff)

        if last_exc:
            raise last_exc
        if last_response is not None:
            last_response.raise_for_status()
            return last_response  # unreachable, but satisfies type checker
        raise RuntimeError(f"[{self.name}] {method} failed with no response: {url}")

    def get(self, url: str, **kwargs) -> httpx.Response:
        """Rate-limited GET with retry on transient errors."""
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        """Rate-limited POST with retry on transient errors."""
        return self._request("POST", url, **kwargs)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def scrape(self) -> dict:
        """Fetch and parse new opportunities from the portal.

        Implementations should:
        - Take NO arguments (store is set at __init__).
        - Use self.get() for HTTP requests (handles retry + rate limit).
        - Call classify_opportunity() on each result to set tier/matched_keywords.
        - Handle start_run/end_run internally.
        - Set self._last_run = datetime.now(timezone.utc) on success.

        Returns:
            Stats dict: {"records_found": int, "records_matched": int, "records_new": int}
        """
        ...

    def _mark_success(self) -> None:
        """Record a successful scrape run. Call at the end of scrape()."""
        self._last_run = datetime.now(timezone.utc)
        logger.info("[%s] Scrape complete. last_run=%s", self.name, self._last_run.isoformat())
