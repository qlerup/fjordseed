import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(os.name!='nt',reason='Native Windows message callback and Tcl event loop')
def test_native_wake_and_tray_clicks_do_not_reenter_tk():
    # Keep a possible native interpreter abort isolated from the test runner.
    source=Path(__file__).resolve().parent
    script=r'''
import tkinter as tk,tempfile,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from windows_background import Tray
root=tk.Tk();root.root_dir=Path(tempfile.gettempdir())/'fjord-tray-regression';root.withdraw()
count=[0]
def show():
    count[0]+=1
    root.deiconify();root.update_idletasks();root.withdraw()
tray=Tray(root,Path(sys.argv[1])/'fjord.ico',show,root.destroy)
sent=[0]
def tick():
    if sent[0]<60:
        message=tray.wake if sent[0]%2==0 else tray.MESSAGE
        tray.user.PostMessageW(tray.hwnd,message,0,0 if sent[0]%2==0 else 0x203)
        sent[0]+=1
    if count[0]>=60:
        print('PASS 60 native wake/click events',flush=True);root.destroy();return
    root.after(10,tick)
root.after(50,tick)
root.after(6000,root.destroy)
root.mainloop()
assert count[0]>=60,count
'''
    result=subprocess.run([sys.executable,'-X','faulthandler','-c',script,str(source)],
                          capture_output=True,text=True,timeout=12)
    assert result.returncode==0,result.stderr
    assert 'PASS 60 native wake/click events' in result.stdout
