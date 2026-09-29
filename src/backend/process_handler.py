import ctypes
import subprocess
import time
from screeninfo import get_monitors
import tkinter as tk
from PIL import Image, ImageTk
import threading
import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from shared.config import *

# Platform-specific imports
if config.platform == "windows":
    import pywintypes
    import win32api
    import win32con
    import win32process
    import win32gui

    # Windows API constants
    PROCESS_ALL_ACCESS = 0x1F0FFF
    PROCESS_VM_OPERATION = 0x0008
    PROCESS_VM_READ = 0x0010
    PROCESS_VM_WRITE = 0x0020
    PROCESS_QUERY_INFORMATION = 0x0400

    # Define functions from kernel32.dll
    OpenProcess = ctypes.windll.kernel32.OpenProcess
    ReadProcessMemory = ctypes.windll.kernel32.ReadProcessMemory
    WriteProcessMemory = ctypes.windll.kernel32.WriteProcessMemory
    CloseHandle = ctypes.windll.kernel32.CloseHandle
    VirtualProtectEx = ctypes.windll.kernel32.VirtualProtectEx

elif config.platform == "linux":
    pass

# ── Linux / Wine: finding the real game process ─────────────────────────────
# Under Wine the process we launch is not necessarily the game, in more than
# one way:
#   * with Rugby08Launcher.exe, the launcher starts Rugby08.exe and exits a
#     few seconds later, leaving the game orphaned (reparented to init);
#   * launching Rugby08.exe directly still goes through Wine's own loader
#     chain (wine -> wine-preloader -> the guest binary), and depending on
#     the Wine build that can also be more than one Unix process: a
#     short-lived wrapper pid that Wine has *already* renamed to
#     "Rugby08.exe" (cosmetic ps output) can be alive briefly alongside, or
#     just before, the real long-lived game pid of the same name.
# Consequences: the pid we got from Popen may die soon, memory read from it
# (while it still lives) may belong to a wrapper and not the game, and with
# kernel.yama.ptrace_scope=1 an orphan can't be read through /proc/<pid>/mem
# since it is no longer our descendant. So become a "child subreaper" before
# launching (orphans are then reparented to us and stay readable), look the
# game up by its process name, and never trust the *first* pid seen with that
# name — wait for it to settle, and always prefer the newest one, so a
# transient wrapper can't be mistaken for the game itself.
GAME_PROCESS_NAME = "Rugby08.exe"
GAME_PROCESS_SETTLE = 0.5   # seconds a matching pid must survive before it is trusted

from shared.log import get_logger

log = get_logger(__name__)


def become_subreaper():
    """Linux only, best-effort: have orphaned descendants reparented to this
    process instead of init, so they stay readable under ptrace_scope=1."""
    try:
        import ctypes.util
        PR_SET_CHILD_SUBREAPER = 36
        libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6", use_errno=True)
        return libc.prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0
    except Exception as e:
        log.warning(f"Could not become a child subreaper: {e}")
        return False

def find_game_pids(name=GAME_PROCESS_NAME):
    """PIDs of running (non-zombie) processes named `name` (Linux)."""
    import psutil
    pids = set()
    for proc in psutil.process_iter(["pid", "name", "status"]):
        try:
            if proc.info["name"] == name and proc.info["status"] != psutil.STATUS_ZOMBIE:
                pids.add(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return pids

class LinuxGameHandle:
    """Popen-like handle (pid + poll()) for a game process we did not start
    ourselves — see above. poll() reaps it if it became our child."""
    def __init__(self, pid):
        self.pid = pid

    def poll(self):
        import psutil
        try:
            proc = psutil.Process(self.pid)
            if proc.status() != psutil.STATUS_ZOMBIE:
                return None
        except psutil.NoSuchProcess:
            return 0
        try:
            os.waitpid(self.pid, os.WNOHANG)   # only succeeds for our own children
        except OSError:
            pass
        return 0

def _candidate_game_pids(launched, pids_before):
    """Currently-alive pids named GAME_PROCESS_NAME that weren't already
    running before we launched — including `launched` itself, whether Wine
    renamed it in place or not."""
    import psutil
    pids = find_game_pids() - pids_before
    try:
        if psutil.Process(launched.pid).name() == GAME_PROCESS_NAME:
            pids.add(launched.pid)
    except psutil.NoSuchProcess:
        pass
    return pids

def _newest_pid(pids):
    """Of several same-named candidates (a dying wrapper alongside the real
    game, or a stale one not yet reaped), the one that started last — a
    wrapper always starts before the child it hands off to."""
    import psutil
    best_pid, best_time = None, -1
    for pid in pids:
        try:
            create_time = psutil.Process(pid).create_time()
        except psutil.NoSuchProcess:
            continue
        if create_time > best_time:
            best_pid, best_time = pid, create_time
    return best_pid

def resolve_linux_game_process(launched, pids_before, timeout=60.0, settle=GAME_PROCESS_SETTLE):
    """(pid, handle) of the game for a process we just launched. That is the
    launched process itself when it is the game, else the new "Rugby08.exe" it
    started (Rugby08Launcher.exe case, or a Wine wrapper/preloader hand-off
    even for a direct launch). A candidate pid is only trusted once it has
    stayed alive, unchanged, for `settle` seconds, so a short-lived wrapper
    that happens to share the game's process name is never mistaken for the
    real, long-lived game process. Falls back to the launched process."""
    deadline = time.time() + timeout
    candidate, candidate_since = None, None
    dead_since = None
    while time.time() < deadline:
        current = _candidate_game_pids(launched, pids_before)
        pid = _newest_pid(current) if current else None
        if pid != candidate:
            candidate, candidate_since = pid, time.time()
        elif candidate is not None and time.time() - candidate_since >= settle:
            log.info(f"Game process: PID {candidate} (launched PID {launched.pid})")
            return candidate, (launched if candidate == launched.pid else LinuxGameHandle(candidate))
        if pid is None:
            if launched.poll() is not None:
                # The launched process is gone and nothing matching has shown
                # up yet; give it a couple more seconds (it may still be
                # handing off to the real game process) before giving up.
                dead_since = dead_since or time.time()
                if time.time() - dead_since >= 2.0:
                    break
        else:
            dead_since = None
        time.sleep(0.1)
    # Timed out or the launch failed: settle for whatever is left rather than
    # blindly trusting `launched` (which may be a dead wrapper).
    current = _candidate_game_pids(launched, pids_before)
    pid = _newest_pid(current) if current else None
    if pid is not None:
        return pid, (launched if pid == launched.pid else LinuxGameHandle(pid))
    return launched.pid, launched

# Return the Windows process handle for a given PID
def get_windows_process_handle(pid):

    if config.platform == "windows":
        process_handle = ctypes.windll.kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not process_handle:
            raise ctypes.WinError(ctypes.get_last_error())
        log.debug(f"Opened process handle: {process_handle}")
        return process_handle

# Check if a process is running
def is_process_running(process_handle):
    # Windows
    if config.platform == "windows":
        return get_process_exit_code(process_handle) == win32con.STILL_ACTIVE

    # Linux
    else:
        return process_handle.poll() == None

# Return the process exit code
def get_process_exit_code(process_handle):
    # Windows
    if config.platform == "windows":
        exit_code = win32process.GetExitCodeProcess(process_handle)
    
    # Linux
    else:
        exit_code = process_handle.poll()
    
    return exit_code

# Read a memory area for a given process
def read_memory(process_handle, address, size):
    if config.simulation_mode:
        return

    try:
        # Windows
        if config.platform == "windows":
            buffer = ctypes.create_string_buffer(size)
            bytes_read = ctypes.c_size_t()
            if not ReadProcessMemory(process_handle, address, buffer, size, ctypes.byref(bytes_read)):
                raise ctypes.WinError(ctypes.get_last_error())
            return buffer.raw

        # Linux
        else:
            with open(f"/proc/{process_handle.pid}/mem", "rb") as fd:
                fd.seek(address)
                return fd.read(size)

    except Exception as e:
        log.debug(f"Failed to read memory: {e}")   # polled every 100 ms: expected while the game starts or exits

# Edit a memory area for a given process
def modify_memory(pid, address, data):
    if config.simulation_mode:
        return

    if config.platform == "windows":
        process_handle = OpenProcess(PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not process_handle:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_string_buffer(data)
        bytes_written = ctypes.c_size_t()
        result = WriteProcessMemory(process_handle, address, buffer, len(data), ctypes.byref(bytes_written))
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        log.debug(f"Successfully wrote {bytes_written.value} bytes to address 0x{address:08X}")
        CloseHandle(process_handle)
    else:
        with open(f"/proc/{pid}/mem", "r+b", buffering=0) as fd:
            fd.seek(address)
            fd.write(data)
        log.debug(f"Successfully wrote {len(data)} bytes to address 0x{address:08X}")

# Return a dump of a memory area for a given process
def dump_memory(process_handle, start_address, end_address):
    if config.simulation_mode:
        return None

    size = end_address - start_address
    if size <= 0:
        raise ValueError("End address must be greater than start address.")

    return read_memory(process_handle, start_address, size)


    if config.platform == "windows":
        buffer = ctypes.create_string_buffer(size)
        bytes_read = ctypes.c_size_t()
        result = ReadProcessMemory(process_handle, start_address, buffer, size, ctypes.byref(bytes_read))
        if not result:
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.raw
    else:
        return None

# Start a process and minimize it
def start_process(executable_path, executable_arguments=None, working_directory=None, process_environment=None):
    if config.simulation_mode:
        return

    if config.platform == "windows":
        startup_info = win32process.STARTUPINFO()
        startup_info.dwFlags |= win32process.STARTF_USESHOWWINDOW
        startup_info.wShowWindow = win32con.SW_MINIMIZE
        try:
            _, _, process_id, _ = win32process.CreateProcess(
                None,
                executable_path,
                None,
                None,
                False,
                win32con.CREATE_NO_WINDOW,
                process_environment,
                working_directory,
                startup_info
            )
            return (process_id, None)
        except Exception as e:
            log.error(f"Error starting process: {e}")
            return None
    elif config.platform == "linux":
        if config.no_R08_process_stdout:
            stdout_dest = subprocess.DEVNULL
        else:
            stdout_dest = sys.stdout

        cmd = [executable_path] + (executable_arguments or [])
        become_subreaper()

        log.debug(f"Environment variables: {process_environment}")
        
        log.debug(f"Running {cmd} in {working_directory}")
        process = subprocess.Popen(
            cmd,
            stdout=stdout_dest,
            cwd=working_directory,
            env=process_environment,
            start_new_session=True
        )
        return (process.pid, process)

def make_window_topmost(window):
    if config.simulation_mode:
        return

    if config.platform == "windows":
        hwnd = win32gui.FindWindow(None, window.title())
        win32gui.SetWindowPos(
            hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
            win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
        )
    else:
        # On Linux, use wmctrl (must be installed)
        try:
            subprocess.run(["wmctrl", "-r", window.title(), "-b", "add,above"], check=True)
        except subprocess.CalledProcessError as e:
            log.error(f"Error setting window topmost: {e}")
