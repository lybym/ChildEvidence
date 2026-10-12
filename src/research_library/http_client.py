"""HTTP client with per-host throttling, retries, disk cache and API logging.

Uses only the standard library (urllib). Designed for polite, low-volume
access to official public APIs (OpenAlex, Crossref, Europe PMC, PubMed,
ERIC, Unpaywall, Semantic Scholar).
"""

from __future__ import annotations

import base64
import hashlib
import json
import random
import re
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RETRY_STATUS = {429, 500, 502, 503, 504}
CHUNK = 64 * 1024


def _backoff(attempt: int, retry_after: str | None = None) -> float:
    if retry_after:
        try:
            return min(float(retry_after), 120.0)
        except ValueError:
            pass
    return min(2.0 * (2 ** (attempt - 1)) + random.uniform(0, 0.5), 30.0)


def _build_url(url: str, params: dict | None) -> str:
    if not params:
        return url
    sep = "&" if "?" in url else "?"
    return url + sep + urllib.parse.urlencode(params)


def _cache_key(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()


class HttpClient:
    def __init__(
        self,
        cache_dir: Path,
        *,
        user_agent: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        host_min_interval: dict | None = None,
        api_log_fn=None,
        cache_ttl_days: float = 7.0,
    ):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.user_agent = user_agent
        self.timeout = timeout
        self.max_retries = max_retries
        self.host_min_interval = host_min_interval or {}
        self.api_log_fn = api_log_fn
        self.cache_ttl_days = cache_ttl_days
        self._last_req: dict[str, float] = {}
        self._ctx = ssl.create_default_context()

    # ------------------------------------------------------------------ util
    def _throttle(self, url: str) -> None:
        host = urllib.parse.urlsplit(url).netloc
        interval = self.host_min_interval.get(host, 0.25)
        now = time.monotonic()
        last = self._last_req.get(host)
        if last is not None:
            wait = interval - (now - last)
            if wait > 0:
                time.sleep(wait)
        self._last_req[host] = time.monotonic()

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (_cache_key(url) + ".json")

    def _log(self, source, url, status, ok, ms, error):
        if self.api_log_fn:
            try:
                self.api_log_fn(source=source, endpoint=url, http_status=status, ok=ok, ms=ms, error=error)
            except Exception:
                pass

    # ------------------------------------------------------------------ GET
    def get(self, url, *, source=None, params=None, headers=None,
            use_cache=True, ttl_days=None, accept="application/json, text/html;q=0.7, */*;q=0.4"):
        """GET a URL and return a dict: url/status/content_type/json/body_text/from_cache/error."""
        full_url = _build_url(url, params)
        ttl = ttl_days if ttl_days is not None else self.cache_ttl_days
        cpath = self._cache_path(full_url)
        if use_cache and cpath.exists():
            try:
                rec = json.loads(cpath.read_text(encoding="utf-8"))
                if time.time() - rec.get("at", 0) <= ttl * 86400:
                    out = _record_to_out(rec, from_cache=True)
                    return out
            except Exception:
                pass

        req_headers = {"User-Agent": self.user_agent, "Accept": accept}
        if headers:
            req_headers.update(headers)
        attempt = 0
        t0 = time.time()
        last_err = None
        while True:
            attempt += 1
            self._throttle(full_url)
            try:
                req = urllib.request.Request(full_url, headers=req_headers)
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as resp:
                    body = resp.read()
                    rec = {
                        "url": full_url,
                        "status": resp.status,
                        "content_type": resp.headers.get("Content-Type", "") or "",
                        "at": time.time(),
                        "body_b64": base64.b64encode(body).decode("ascii"),
                    }
                    if use_cache:
                        try:
                            cpath.write_text(json.dumps(rec), encoding="utf-8")
                        except Exception:
                            pass
                    self._log(source, full_url, resp.status, True, int((time.time() - t0) * 1000), None)
                    return _record_to_out(rec, from_cache=False)
            except urllib.error.HTTPError as e:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                last_err = f"HTTP {e.code}"
                if e.code in RETRY_STATUS and attempt <= self.max_retries:
                    time.sleep(_backoff(attempt, retry_after))
                    continue
                self._log(source, full_url, e.code, False, int((time.time() - t0) * 1000), last_err)
                return {"url": full_url, "status": e.code, "content_type": "", "json": None,
                        "body_text": "", "from_cache": False, "error": last_err}
            except Exception as e:  # URLError, timeouts, SSL, DNS
                last_err = repr(e)[:200]
                if attempt <= self.max_retries:
                    time.sleep(_backoff(attempt))
                    continue
                self._log(source, full_url, None, False, int((time.time() - t0) * 1000), last_err)
                return {"url": full_url, "status": None, "content_type": "", "json": None,
                        "body_text": "", "from_cache": False, "error": last_err}

    # ------------------------------------------------------------- download
    def download_to(self, url, dest_path: Path, *, source=None, headers=None,
                    max_bytes: int = 300 * 1024 * 1024):
        """Stream a file to dest_path. Returns dict with status/file info or error."""
        req_headers = {"User-Agent": self.user_agent,
                       "Accept": "application/pdf, application/octet-stream, */*;q=0.5"}
        if headers:
            req_headers.update(headers)
        attempt = 0
        t0 = time.time()
        while True:
            attempt += 1
            self._throttle(url)
            try:
                req = urllib.request.Request(url, headers=req_headers)
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ctx) as resp:
                    ctype = resp.headers.get("Content-Type", "") or ""
                    h = hashlib.sha256()
                    size = 0
                    dest_path = Path(dest_path)
                    dest_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(dest_path, "wb") as f:
                        while True:
                            chunk = resp.read(CHUNK)
                            if not chunk:
                                break
                            size += len(chunk)
                            if size > max_bytes:
                                raise ValueError("file exceeds max_bytes limit")
                            h.update(chunk)
                            f.write(chunk)
                    result = {
                        "url": url,
                        "status": resp.status,
                        "http_headers": {k: v for k, v in resp.headers.items()},
                        "content_type": ctype,
                        "file_path": str(dest_path),
                        "file_size": size,
                        "sha256": h.hexdigest(),
                        "error": None,
                        "final_url": resp.geturl(),
                    }
                    self._log(source, url, resp.status, True, int((time.time() - t0) * 1000), None)
                    return result
            except urllib.error.HTTPError as e:
                retry_after = e.headers.get("Retry-After") if e.headers else None
                if e.code in RETRY_STATUS and attempt <= self.max_retries:
                    time.sleep(_backoff(attempt, retry_after))
                    continue
                self._log(source, url, e.code, False, int((time.time() - t0) * 1000), f"HTTP {e.code}")
                return {"url": url, "status": e.code, "content_type": "", "file_path": None,
                        "file_size": 0, "sha256": None, "error": f"HTTP {e.code}"}
            except Exception as e:
                if attempt <= self.max_retries and not isinstance(e, ValueError):
                    time.sleep(_backoff(attempt))
                    continue
                self._log(source, url, None, False, int((time.time() - t0) * 1000), repr(e)[:200])
                return {"url": url, "status": None, "content_type": "", "file_path": None,
                        "file_size": 0, "sha256": None, "error": repr(e)[:200]}


def _record_to_out(rec: dict, from_cache: bool) -> dict:
    body = base64.b64decode(rec.get("body_b64") or "")
    ctype = rec.get("content_type", "")
    body_text = ""
    payload = None
    if "json" in ctype or (body[:1] in (b"{", b"[")):
        try:
            payload = json.loads(body.decode("utf-8", "replace"))
        except Exception:
            payload = None
    body_text = body.decode("utf-8", "replace")
    return {
        "url": rec.get("url"),
        "status": rec.get("status"),
        "content_type": ctype,
        "json": payload,
        "body_text": body_text,
        "from_cache": from_cache,
        "fetched_at": rec.get("at"),
        "error": None,
    }
