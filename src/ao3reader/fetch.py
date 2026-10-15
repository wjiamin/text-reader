"""Getting a work's page from AO3: one request for the whole work, nothing more."""

import re
import sys
import time
from collections.abc import Callable

import httpx

from . import __version__

BASE_URL = "https://archiveofourown.org"
USER_AGENT = (
    f"ao3-reader/{__version__} (personal text-to-speech; "
    "https://github.com/wjiamin/text-reader)"
)

SAVE_PAGE_TIP = (
    "Open the work in your browser (logged in if needed), click 'Entire Work', "
    "save the page (Ctrl+S, or Cmd+S on a Mac), then give ao3-reader the saved "
    ".html file instead of the link."
)

_WORK_ID = re.compile(r"/works/(\d+)")


class FetchError(Exception):
    pass


def parse_work_id(ref: str) -> int:
    """Accept a bare work ID or any AO3 link to a work or one of its chapters."""
    ref = ref.strip()
    if ref.isdigit():
        return int(ref)
    if match := _WORK_ID.search(ref):
        return int(match.group(1))
    raise ValueError(f"Not an AO3 work link or work ID: {ref!r}")


def work_url(work_id: int) -> str:
    return f"{BASE_URL}/works/{work_id}"


def fetch_work(
    work_id: int,
    *,
    client: httpx.Client | None = None,
    retries: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    """Download every chapter of a work as one page, skipping the adult-content prompt."""
    url = f"{work_url(work_id)}?view_full_work=true&view_adult=true"
    owns_client = client is None
    if client is None:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=60
        )
    try:
        for attempt in range(retries + 1):
            response = client.get(url)
            if response.status_code != 429 or attempt == retries:
                break
            wait = _retry_after(response)
            print(f"AO3 asked us to slow down, waiting {wait:.0f}s...", file=sys.stderr)
            sleep(wait)
    except httpx.HTTPError as error:
        raise FetchError(f"Couldn't reach AO3: {error}") from error
    finally:
        if owns_client:
            client.close()

    _check(response, work_id)
    return response.text


def _retry_after(response: httpx.Response) -> float:
    try:
        seconds = float(response.headers.get("Retry-After", 60))
    except ValueError:
        seconds = 60
    return min(max(seconds, 5), 300)


def _check(response: httpx.Response, work_id: int) -> None:
    status = response.status_code
    if status == 404:
        raise FetchError(
            f"Work {work_id} wasn't found. It may have been deleted, or the link is wrong."
        )
    if status == 429:
        raise FetchError("AO3 is limiting requests right now. Wait a few minutes and try again.")
    if "/users/login" in response.url.path or (
        "only available to registered users" in response.text
    ):
        raise FetchError(
            f"Work {work_id} is only visible to logged-in AO3 users. {SAVE_PAGE_TIP}"
        )
    if status in (403, 503) and (
        "cf-ray" in response.headers or "Just a moment" in response.text
    ):
        raise FetchError(f"AO3's bot protection blocked the download. {SAVE_PAGE_TIP}")
    if status != 200:
        raise FetchError(f"AO3 answered with HTTP {status} for work {work_id}.")
