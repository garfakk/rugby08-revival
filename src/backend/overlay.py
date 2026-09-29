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

def get_screen_resolution():
    if config.simulation_mode:
        return

    for screen_info in get_monitors():
        if screen_info.is_primary:
            return (screen_info.width, screen_info.height)

    return None

def change_screen_resolution(resolution):
    if config.simulation_mode:
        return

    if config.platform == "windows":
        devmode = pywintypes.DEVMODEType()
        devmode.PelsWidth = resolution[0]
        devmode.PelsHeight = resolution[1]
        devmode.Fields = win32con.DM_PELSWIDTH | win32con.DM_PELSHEIGHT
        win32api.ChangeDisplaySettings(devmode, 0)
    else:
        # On Linux, use xrandr (requires subprocess and root/sudo)
        cmd = f"xrandr --output $(xrandr | grep ' connected' | cut -d' ' -f1) --mode {resolution[0]}x{resolution[1]}"
        subprocess.run(cmd, shell=True, check=True)




def display_fullscreen_image(image_path):
    if config.simulation_mode:
        return

    def run_display():
        root = tk.Tk()
        root.attributes("-fullscreen", True)
        root.configure(bg="black")

        img = Image.open(image_path)
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        img = img.resize((screen_width, screen_height))
        img_tk = ImageTk.PhotoImage(img)

        label = tk.Label(root, image=img_tk, bg="black")
        label.place(x=0, y=0, relwidth=1, relheight=1)

        root.after(100, lambda: make_window_topmost(root))
        root.bind("<Key>", lambda e: root.destroy())
        root.bind("<Button-1>", lambda e: root.destroy())

        root.mainloop()

    thread = threading.Thread(target=run_display, daemon=True)
    thread.start()


