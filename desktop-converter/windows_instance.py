"""One background process per installed copy, with a tray wake-up message."""
import atexit
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path

_handle=None


def identity(root):return hashlib.sha256(str(Path(root).resolve()).casefold().encode()).hexdigest()[:24]


def wake_message(root):
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.RegisterWindowMessageW.argtypes=[wintypes.LPCWSTR]
    user.RegisterWindowMessageW.restype=wintypes.UINT
    return user.RegisterWindowMessageW('FjordConverterWake-'+identity(root))


def acquire(root):
    global _handle
    if os.name!='nt':return True
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    ctypes.set_last_error(0)
    handle=kernel.CreateMutexW(None,False,'Local\\FjordConverter-'+identity(root))
    if not handle:raise ctypes.WinError(ctypes.get_last_error())
    if ctypes.get_last_error()==183:
        kernel.CloseHandle(handle)
        user=ctypes.WinDLL('user32',use_last_error=True)
        user.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
        user.PostMessageW(0xffff,wake_message(root),0,0)
        return False
    _handle=handle
    atexit.register(lambda:kernel.CloseHandle(handle))
    return True
