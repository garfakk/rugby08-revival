"""TEMPORARY debug helper (first-launch bug: the game sometimes runs WITHOUT the
d3d8 proxy, for every match of one UI session, then never again after the UI is
restarted). Logs what differs between UI sessions: the launcher's own context
(parent chain, elevation, integrity, image-load mitigation, compat env) and,
a few seconds after each game start, which d3d8.dll the game really mapped.

Remove this file and its two calls in R08_handler once the bug is fixed.
"""
import ctypes
import os
import threading
import time
from ctypes import wintypes

from shared.log import get_logger

log = get_logger(__name__)


def _elevation_and_integrity(pid):
    """(elevated, integrity RID hex) of a process, best effort."""
    try:
        import win32api, win32con, win32process, win32security
        h = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, pid)
        tok = win32security.OpenProcessToken(h, win32con.TOKEN_QUERY)
        elevated = win32security.GetTokenInformation(tok, 20)   # TokenElevation
        sid, _attrs = win32security.GetTokenInformation(tok, 25)  # TokenIntegrityLevel
        rid = sid.GetSubAuthority(sid.GetSubAuthorityCount() - 1)
        return bool(elevated), f"0x{rid:04x}"
    except Exception as e:
        return None, f"? ({e})"


def _image_load_policy(pid):
    """ProcessImageLoadPolicy flags (bit0 NoRemoteImages, bit1 NoLowMandatoryLabel,
    bit2 PreferSystem32Images, ...) of a process, best effort."""
    try:
        import win32api, win32con
        h = win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION, False, pid)
        buf = ctypes.c_uint32(0)
        fn = ctypes.windll.kernel32.GetProcessMitigationPolicy
        fn.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t]
        ok = fn(int(h), 10, ctypes.byref(buf), ctypes.sizeof(buf))   # 10 = ProcessImageLoadPolicy
        return f"0x{buf.value:x}" if ok else "unavailable"
    except Exception as e:
        return f"? ({e})"


def _describe(pid, label):
    import psutil
    try:
        p = psutil.Process(pid)
        elevated, rid = _elevation_and_integrity(pid)
        env = {}
        try:
            env = p.environ()
        except Exception:
            pass
        log.info(f"[diag] {label} pid={pid} name={p.name()} exe={p.exe()} user={p.username()} "
                 f"elevated={elevated} integrity={rid} imageLoadPolicy={_image_load_policy(pid)} "
                 f"cwd={_safe(p.cwd)}")
        for k in ("__COMPAT_LAYER", "__PROCESS_HISTORY", "PROCESSOR_ARCHITEW6432", "SESSIONNAME", "USERPROFILE"):
            if k in env:
                log.info(f"[diag]   {label} env {k}={env[k]}")
        path = env.get("PATH") or env.get("Path") or ""
        log.info(f"[diag]   {label} PATH head: {path[:300]}")
        return p
    except Exception as e:
        log.info(f"[diag] {label} pid={pid}: cannot describe ({e})")
        return None


def _safe(fn):
    try:
        return fn()
    except Exception as e:
        return f"? ({e})"


def log_launcher_context():
    """Once per game start: the UI process, its parent chain and its environment."""
    try:
        import psutil
        me = psutil.Process(os.getpid())
        _describe(me.pid, "ui")
        parent = me.parent()
        depth = 0
        while parent is not None and depth < 4:
            _describe(parent.pid, f"ui-parent{depth}")
            parent = _safe(parent.parent)
            depth += 1
            if isinstance(parent, str):
                break
        log.info(f"[diag] ui started {time.time() - me.create_time():.0f} s ago; "
                 f"__COMPAT_LAYER={os.environ.get('__COMPAT_LAYER')!r}")
    except Exception as e:
        log.info(f"[diag] launcher context failed: {e}")


def _watch(pid, exe_dir):
    import psutil
    seen_real = None
    t0 = time.time()
    for delay in (1.0, 2.0, 3.0, 5.0, 8.0):
        time.sleep(max(0.0, delay - (time.time() - t0)))
        try:
            p = psutil.Process(pid)
            maps = {m.path.lower() for m in p.memory_maps(grouped=True)}
        except Exception as e:
            log.info(f"[diag] +{delay:.0f}s game pid={pid}: cannot read modules ({e})")
            if not psutil.pid_exists(pid):
                return
            continue
        d3d = sorted(m for m in maps if m.endswith("\\d3d8.dll") or m.endswith("\\d3d8d.dll"))
        ours = [m for m in maps if m.endswith("rugby08patches.dll") or m.endswith("r08dbg.dll")]
        log.info(f"[diag] +{delay:.0f}s game pid={pid}: d3d8 mapped from {d3d or 'NOT LOADED YET'}; "
                 f"patches/dbg dlls={ours or 'none'}; {len(maps)} modules")
        if delay == 1.0:
            _describe(pid, "game")
        # the proxy lives in the exe dir; the system one in System32/SysWOW64
        seen_real = any(exe_dir.lower() in m for m in d3d)
        if seen_real:
            break
    if not seen_real:
        log.warning("[diag] the game did NOT map the proxy d3d8.dll from its own folder")



def watch_game_modules(pid, exe_dir):
    """Background: a few seconds after the game start, log which d3d8.dll it mapped."""
    threading.Thread(target=_watch, args=(pid, exe_dir), daemon=True, name="diag-modules").start()
