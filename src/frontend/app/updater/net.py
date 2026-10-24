"""
app/updater/net.py — the little HTTPS client the updater needs.

urllib only (no new dependency), an honest User-Agent, timeouts, a few
retries with backoff for transient failures, and GitHub's rate limit turned
into a readable error. Downloads go to <dest>.part and are renamed only once
complete and (when a sha256 is given) verified, so nothing half-written or
tampered with is ever left where it would be used.

Tests swap `opener` for a fake (see tests/unit/test_updater.py).
"""
import hashlib
import json
import os
import time
import urllib.error
import urllib.request

from shared.version import APP_VERSION

USER_AGENT = f"Rugby08Revival/{APP_VERSION} (+updater)"
TIMEOUT_S = 30
RETRIES = 3
BACKOFF_S = 1.5
CHUNK = 1 << 16


class NetError(Exception):
    """Anything that kept a request from succeeding, in words for the user."""


class Cancelled(Exception):
    pass


def opener(request, timeout):
    """The one place a connection is opened (replaced in tests)."""
    return urllib.request.urlopen(request, timeout=timeout)


def _request(url, accept=None):
    headers = {"User-Agent": USER_AGENT}
    if accept:
        headers["Accept"] = accept
    return urllib.request.Request(url, headers=headers)


def _explain(exc, url):
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 403 and exc.headers.get("X-RateLimit-Remaining") == "0":
            reset = exc.headers.get("X-RateLimit-Reset")
            wait = ""
            if reset and reset.isdigit():
                wait = f" Try again in {max(1, int((int(reset) - time.time()) // 60) + 1)} min."
            return NetError("GitHub's limit of requests per hour was reached." + wait)
        if exc.code == 404:
            return NetError(f"not found on the server ({url})")
        return NetError(f"the server answered {exc.code} {exc.reason}")
    if isinstance(exc, urllib.error.URLError):
        return NetError(f"no connection ({exc.reason})")
    return NetError(str(exc) or exc.__class__.__name__)


def _retrying(fn, url):
    last = None
    for attempt in range(RETRIES):
        try:
            return fn()
        except Cancelled:
            raise
        except urllib.error.HTTPError as e:
            last = e
            if e.code < 500 and e.code != 429:      # a client error won't fix itself
                break
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            last = e
        time.sleep(BACKOFF_S * (attempt + 1))
    raise _explain(last, url)


def get_json(url):
    def go():
        with opener(_request(url, "application/vnd.github+json"), TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    try:
        return _retrying(go, url)
    except ValueError as e:
        raise NetError(f"unreadable answer from {url}: {e}") from e


def get_text(url):
    def go():
        with opener(_request(url), TIMEOUT_S) as resp:
            return resp.read().decode("utf-8", "replace")
    return _retrying(go, url)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest, sha256=None, progress=None, cancel=None):
    """Fetch `url` into `dest`. `progress(bytes_so_far)` is called as it
    goes, `cancel()` returning True stops it (Cancelled). With `sha256`, a
    file that doesn't match is discarded (NetError)."""
    part = dest + ".part"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)

    def go():
        got = 0
        h = hashlib.sha256()
        with opener(_request(url), TIMEOUT_S) as resp, open(part, "wb") as fh:
            while True:
                if cancel and cancel():
                    raise Cancelled()
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                fh.write(chunk)
                h.update(chunk)
                got += len(chunk)
                if progress:
                    progress(got)
        if sha256 and h.hexdigest() != sha256.lower():
            raise NetError(f"{os.path.basename(dest)}: the downloaded file is not the expected one "
                           "(checksum mismatch)")
        return got

    try:
        size = _retrying(go, url)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise
    os.replace(part, dest)
    return size
