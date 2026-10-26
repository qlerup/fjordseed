"""Opt-in startup for the current Windows user; no administrator rights."""
import os
from pathlib import Path
import subprocess
import sys

KEY=r'Software\Microsoft\Windows\CurrentVersion\Run'
NAME='FjordConverter'


def command(script):
    if getattr(sys,'frozen',False):return subprocess.list2cmdline([sys.executable,'--background'])
    python=Path(sys.executable).with_name('pythonw.exe')
    return subprocess.list2cmdline([str(python),str(Path(script).resolve()),'--background'])


def enabled(script):
    if os.name!='nt':return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,KEY) as key:
            value,kind=winreg.QueryValueEx(key,NAME)
        return kind==winreg.REG_SZ and value==command(script)
    except FileNotFoundError:return False


def configure(script,enable):
    if os.name!='nt':raise OSError('Automatisk opstart kræver Windows.')
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,KEY,0,winreg.KEY_SET_VALUE) as key:
        if enable:winreg.SetValueEx(key,NAME,0,winreg.REG_SZ,command(script))
        else:
            try:winreg.DeleteValue(key,NAME)
            except FileNotFoundError:pass
