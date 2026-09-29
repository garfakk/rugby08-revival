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

if config.platform == "windows":
    import pywintypes
    import win32api
    import win32con
    import win32process
    import win32gui
    import win32con

    tkRoot = None
    global screen_controller_selection_reached
    screen_controller_selection_reached = False
    global R08_pid
    R08_pid = None

    # Windows API constants
    PROCESS_ALL_ACCESS = 0x1F0FFF  # Full access to the process
    PROCESS_VM_READ = 0x0010
    PROCESS_VM_WRITE = 0x0020
    PROCESS_QUERY_INFORMATION = 0x0400

    # Define functions from kernel32.dll
    OpenProcess = ctypes.windll.kernel32.OpenProcess
    ReadProcessMemory = ctypes.windll.kernel32.ReadProcessMemory
    WriteProcessMemory = ctypes.windll.kernel32.WriteProcessMemory
    CloseHandle = ctypes.windll.kernel32.CloseHandle
    VirtualProtectEx = ctypes.windll.kernel32.VirtualProtectEx
    

from shared.log import get_logger

log = get_logger(__name__)


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
        
    if resolution:
        devmode = pywintypes.DEVMODEType()
        devmode.PelsWidth = resolution[0]
        devmode.PelsHeight = resolution[1]

        devmode.Fields = win32con.DM_PELSWIDTH | win32con.DM_PELSHEIGHT
        win32api.ChangeDisplaySettings(devmode, 0)


def make_window_topmost(window):
    if config.simulation_mode:
        return

    hwnd = win32gui.FindWindow(None, window.title())
    win32gui.SetWindowPos(
        hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
        win32con.SWP_NOMOVE | win32con.SWP_NOSIZE
    )

def display_fullscreen_image(image_path):
    if config.simulation_mode:
        return

    def run_display():
        global tkRoot
        
        root = tk.Tk()
        root.attributes("-fullscreen", True)
        root.configure(bg="black")

        # Load and display the image
        img = Image.open(image_path)
        screen_width = root.winfo_screenwidth()
        screen_height = root.winfo_screenheight()
        img = img.resize((screen_width, screen_height))
        img_tk = ImageTk.PhotoImage(img)

        label = tk.Label(root, image=img_tk, bg="black")
        label.place(x=0, y=0, relwidth=1, relheight=1)

        # Make the window always on top
        root.after(100, lambda: make_window_topmost(root))

        # Exit on any key press or mouse click
        root.bind("<Key>", lambda e: root.destroy())
        root.bind("<Button-1>", lambda e: root.destroy())

        tkRoot = root

        root.mainloop()
        

    # Run the tkinter display in a new thread
    thread = threading.Thread(target=run_display, daemon=True)
    thread.start()

#previous_screen_resolution = get_screen_resolution()
#change_screen_resolution((800, 600))


def read_memory(process_handle, address, size):
    if config.simulation_mode:
        return
        
    """
    Reads memory from the target process.
    :param process_handle: Handle to the target process.
    :param address: Memory address to read.
    :param size: Number of bytes to read.
    :return: The read memory bytes in little-endian order.
    """
    buffer = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t()

    # Read process memory
    if not ReadProcessMemory(process_handle, address, buffer, size, ctypes.byref(bytes_read)):
        raise ctypes.WinError(ctypes.get_last_error())
    
    # Return memory bytes directly in little-endian order
    return buffer.raw

def modify_memory(pid, address, data):
    if config.simulation_mode:
        return
        
    """
    Modify memory in the target process at the given address.
    :param pid: The PID of the process.
    :param address: The memory address to modify.
    :param data: The new data to write (as bytes).
    """
    # Open the target process with necessary permissions
    process_handle = OpenProcess(PROCESS_VM_WRITE | PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not process_handle:
        raise ctypes.WinError(ctypes.get_last_error())

    # Write memory at the specified address
    buffer = ctypes.create_string_buffer(data)
    bytes_written = ctypes.c_size_t()

    result = WriteProcessMemory(process_handle, address, buffer, len(data), ctypes.byref(bytes_written))
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())

    log.debug(f"Successfully wrote {bytes_written.value} bytes to address 0x{address:08X}")

    # Close the process handle
    CloseHandle(process_handle)

def dump_memory(process_handle, start_address, end_address):
    if config.simulation_mode:
        return
        
    """
    Dumps memory from start_address to end_address in the target process.
    :param process_handle: Handle to the target process.
    :param start_address: Starting memory address to dump.
    :param end_address: Ending memory address to dump (exclusive).
    :return: The dumped memory bytes.
    """
    size = end_address - start_address
    if size <= 0:
        raise ValueError("End address must be greater than start address.")
    
    buffer = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t()
    result = ReadProcessMemory(process_handle, start_address, buffer, size, ctypes.byref(bytes_read))
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    
    return buffer.raw



def start_process_minimized(executable_path, executable_arguments=None, working_directory=None):
    if config.simulation_mode:
        return
        
    """
    Starts a process minimized and returns its PID.
    :param executable_path: Path to the executable file.
    :param working_directory: Working directory for the process.
    :return: The PID of the started process.
    """
    
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
              None, 
              working_directory, 
              startup_info
          )
          return process_id
          
      except Exception as e:
          log.error(f"Error starting process: {e}")
          return None

    else:
      cmd = [executable_path] + executable_arguments
      process = subprocess.Popen(cmd, cwd=working_directory)
      return process.pid
      

