"""HTTP for the importers. It sends one User-Agent, retries a page a site failed to serve, refuses to cache a page the
site served wrong, and writes the cache atomically.

The module is named net, not http, because tools/ is on sys.path and a tools/http.py would shadow the standard
library's http, which urllib itself imports.

A cached page lives at .cache/<readable prefix>-<sha256 of the URL, 12 hex>. The hash keeps two URLs that differ
only in punctuation apart: "SM1+" and "SM1_" used to share a file. A page cached under the old name, which had no
hash, is moved to the new one the first time it is asked for, not fetched again.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import tempfile
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
VERSION = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
USER_AGENT = f"pkmjson/{VERSION} (+https://github.com/ArthurG-data/pkmjson)"
TRIES = 6
RETRY_STATUS = {429, 500, 502, 503, 504}
MAX_WAIT = 120
MISSING = {"__missing__": True}
_UMASK = os.umask(0)
os.umask(_UMASK)
# What a dropped connection or a body cut short raises, at any point of reading the response.
TRANSIENT = (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException, json.JSONDecodeError)


class UnexpectedPage(Exception):
    """The site answered, but not with the page asked for (a TCGCSV error envelope, a JSON body without the fields
    the caller needs). It is never cached."""


def _wait(error: urllib.error.HTTPError | None, attempt: int) -> float:
    """Seconds to wait before the next try: the server's Retry-After when it gives one in seconds, else 1, 2, 4..."""
    if error is not None and (after := error.headers.get("Retry-After") if error.headers else None):
        try:
            return min(float(after), MAX_WAIT)
        except ValueError:
            pass
    return float(2 ** attempt)


def retried(call: Callable[[], object], tries: int = TRIES, sleep: Callable[[float], None] = time.sleep) -> object:
    """call(), tried again after a 429, a 5xx, a dropped connection or a body cut short. Any other 4xx is final, and
    so is the last failure."""
    for attempt in range(tries):
        try:
            return call()
        except urllib.error.HTTPError as error:
            if error.code not in RETRY_STATUS or attempt == tries - 1:
                raise
            sleep(_wait(error, attempt))
        except TRANSIENT:
            if attempt == tries - 1:
                raise
            sleep(_wait(None, attempt))
    raise AssertionError("unreachable")


def get(url: str, timeout: int = 60, tries: int = TRIES, accept: str = "*/*") -> bytes:
    def call() -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    return retried(call, tries)


def get_json(url: str, timeout: int = 60, tries: int = TRIES) -> object:
    """The JSON document at url. A truncated body is retried like a dropped connection."""
    return retried(lambda: json.loads(get(url, timeout, 1, "application/json").decode("utf-8")), tries)


def get_json_or_none(url: str, timeout: int = 60, tries: int = TRIES) -> object | None:
    """The JSON document at url, or None when the site says it has none (404)."""
    try:
        return get_json(url, timeout, tries)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def write_atomic(path: Path, data: str | bytes) -> None:
    """Write data to path so that a reader sees the old file or the whole new one, never a part of it. An
    interrupted run leaves no truncated file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        os.chmod(tmp, 0o666 & ~_UMASK)   # mkstemp makes the file private; a written file is as open as any other
        with os.fdopen(fd, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def legacy_cache_name(url: str) -> str:
    """The name the cache gave a URL before names carried a hash."""
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("://", 1)[1])
    if len(name) > 120:
        name = f"{name[:70]}_{hashlib.sha1(url.encode()).hexdigest()}"
    return name


def cache_name(url: str) -> str:
    """A readable prefix of the URL and 12 hex digits of its SHA-256, at most 100 characters (eCryptfs allows 143)."""
    prefix = re.sub(r"[^A-Za-z0-9._-]+", "_", url.split("://", 1)[1])[:80].rstrip("._")
    return f"{prefix}-{hashlib.sha256(url.encode()).hexdigest()[:12]}"


def tcgcsv_ok(body: object) -> bool:
    """TCGCSV wraps every answer as {"success": ..., "errors": [...], "results": [...]}: an envelope that reports
    failure is an error page, not data."""
    return not (isinstance(body, dict) and body.get("success") is False)


class Fetcher:
    """GETs JSON, kept on disk so a re-run does not fetch again. A 404 is kept as {"__missing__": true} and read as
    None. With refresh, each URL is fetched again once per run, the 404s included."""

    def __init__(self, cache: Path, pause: float = 0.2, refresh: bool = False,
                 fetch: Callable[[str], object] = get_json, sleep: Callable[[float], None] = time.sleep):
        self.cache, self.pause, self.refresh = cache, pause, refresh
        self._fetch, self._sleep = fetch, sleep
        self._fresh: set[str] = set()

    def path(self, url: str) -> Path:
        """Where url is kept, after moving a copy kept under its old name there."""
        path = self.cache / cache_name(url)
        legacy = self.cache / legacy_cache_name(url)
        if not path.exists() and legacy.exists():
            os.replace(legacy, path)
        return path

    def get(self, url: str, valid: Callable[[object], bool] | None = None) -> dict | list | None:
        """The JSON document at url, or None when there is none. `valid` refuses a document the site served
        wrong: it raises UnexpectedPage, and nothing is cached."""
        path = self.path(url)
        if path.exists() and not (self.refresh and url not in self._fresh):
            body = json.loads(path.read_text(encoding="utf-8"))
            return None if body == MISSING else body
        try:
            body = self._fetch(url)
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            body = MISSING
        if body != MISSING:
            check = valid or (tcgcsv_ok if "tcgcsv.com" in url else None)
            if check is not None and not check(body):
                raise UnexpectedPage(f"{url} did not serve the expected document")
        self._sleep(self.pause)
        write_atomic(path, json.dumps(body, ensure_ascii=False))
        self._fresh.add(url)
        return None if body == MISSING else body

    def get_text(self, url: str, name: str) -> str:
        """A text file (a CSV), kept at .cache/<name>."""
        path = self.cache / name
        if not path.exists() or (self.refresh and url not in self._fresh):
            write_atomic(path, get(url))
            self._fresh.add(url)
        return path.read_text(encoding="utf-8")


def quote(part: str) -> str:
    return urllib.parse.quote(part, safe="")
