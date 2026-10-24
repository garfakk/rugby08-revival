"""
app/updater/program.py — program updates: the program-only installer.

A program release (tag v<version>) carries R08Revival_<version>_program_only.exe
and SHA256SUMS. Updating from the app is: download the installer into
user_data/updates/downloads, check it against its SHA256SUMS line (an
installer without a matching line is never run), then start it, visibly,
upgrading this very folder, and quit; the installer starts the mod again
when it is done (/RELAUNCH=1, see packaging/installer.iss).

Why this shape (antivirus heuristics flag the alternatives):
  - the running program never rewrites its own exe or DLLs, and never drops
    a helper script or batch file to do it after exiting;
  - what runs is the same Inno Setup installer people download by hand,
    started as an ordinary process (no shell, no PowerShell, no hidden
    window: /SILENT shows its progress window), after the user asked for it;
  - nothing is written outside the install folder.

Only for the released (frozen) Windows program: running from source, the
program is updated with git.
"""
import os
import re
import subprocess
import sys
from dataclasses import dataclass

from . import net, releases


class ProgramUpdateError(Exception):
    pass


def supported():
    """The program can update itself: the released Windows build."""
    from shared.app_paths import FROZEN
    return FROZEN and sys.platform == "win32"


@dataclass
class ProgramCheck:
    current: str = ""
    release: object = None          # releases.Release, or None when up to date
    installer: tuple = None         # (name, url, size)
    checksums: str = ""             # SHA256SUMS url
    problem: str = ""               # a newer release exists but can't be installed from here

    @property
    def available(self):
        return self.release is not None


def check(source, current):
    out = ProgramCheck(current=current)
    rel = releases.latest(source["repo"], source.get("tag_prefix", "v"), current)
    if rel is None:
        return out
    out.release = rel
    name = source.get("installer", "R08Revival_{version}_program_only.exe").format(version=rel.version)
    asset, sums = rel.asset(name), rel.asset(source.get("checksums", "SHA256SUMS"))
    if not asset or not sums:
        out.problem = "this release has no program installer to download: get it from its page"
        return out
    out.installer, out.checksums = (name, asset[0], asset[1]), sums[0]
    return out


def parse_sums(text):
    """SHA256SUMS ("<hex>  <name>" or "<hex> *<name>" lines) -> {name: hex}."""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$", line)
        if m:
            out[os.path.basename(m.group(2))] = m.group(1).lower()
    return out


def download(the_check, dest_dir, progress=None, cancel=None):
    """The verified installer's path. `progress(bytes, total)`."""
    if not the_check.installer:
        raise ProgramUpdateError(the_check.problem or "nothing to download")
    name, url, size = the_check.installer
    sha = parse_sums(net.get_text(the_check.checksums)).get(name)
    if not sha:
        raise ProgramUpdateError(f"{name} is not in the release's SHA256SUMS: not downloading it")
    dest = os.path.join(dest_dir, name)
    if os.path.isfile(dest) and net.sha256_of(dest) == sha:
        return dest                                  # downloaded and verified before
    net.download(url, dest, sha256=sha, cancel=cancel,
                 progress=(lambda n: progress(n, size)) if progress else None)
    return dest


def installer_args(path, app_dir):
    return [path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS",
            f"/DIR={app_dir}", "/RELAUNCH=1"]


def launch(path, app_dir, popen=subprocess.Popen):
    """Start the installer (visible progress window) on this install's
    folder. The caller quits the program right after."""
    if not os.path.isfile(path):
        raise ProgramUpdateError("the downloaded installer is gone")
    try:
        popen(installer_args(path, app_dir), cwd=os.path.dirname(path), close_fds=True)
    except OSError as e:
        raise ProgramUpdateError(f"could not start the installer: {e}") from e
