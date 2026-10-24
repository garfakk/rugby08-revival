"""
app/updater/releases.py — the newest GitHub release of a channel.

Both channels can share one repository: the tag prefix tells them apart
(v0.4 = program, data-2026.10.24 = data). Drafts and pre-releases are never
offered.
"""
import re
from dataclasses import dataclass, field

from . import net

API = "https://api.github.com"


def version_key(text):
    """"0.10" > "0.9", "2026.10.24" > "2026.9.30": numbers compared as numbers."""
    return tuple(int(n) for n in re.findall(r"\d+", str(text))) or (0,)


@dataclass
class Release:
    tag: str
    version: str
    name: str = ""
    notes: str = ""
    url: str = ""                                     # the release page
    assets: dict = field(default_factory=dict)        # name -> (download url, size)

    def asset(self, name):
        return self.assets.get(name)


def _parse(item, prefix):
    tag = str(item.get("tag_name") or "")
    if item.get("draft") or item.get("prerelease") or not tag.startswith(prefix):
        return None
    version = tag[len(prefix):]
    if not re.match(r"^\d", version):            # "v" must not also match "video-..."
        return None
    assets = {a.get("name", ""): (a.get("browser_download_url", ""), int(a.get("size") or 0))
              for a in item.get("assets") or [] if a.get("name")}
    return Release(tag=tag, version=version, name=str(item.get("name") or tag),
                   notes=str(item.get("body") or ""), url=str(item.get("html_url") or ""), assets=assets)


def releases(repo, prefix):
    """The channel's published releases, newest version first."""
    data = net.get_json(f"{API}/repos/{repo}/releases?per_page=50")
    if not isinstance(data, list):
        raise net.NetError(f"unexpected answer for {repo}'s releases")
    found = [r for r in (_parse(item, prefix) for item in data if isinstance(item, dict)) if r]
    return sorted(found, key=lambda r: version_key(r.version), reverse=True)


def latest(repo, prefix, current=None, accept=None):
    """The newest release (newer than `current` when given) that `accept`
    (a predicate, default all) takes; None when there is none."""
    for r in releases(repo, prefix):
        if current is not None and version_key(r.version) <= version_key(current):
            return None
        if accept is None or accept(r):
            return r
    return None
