import os
import queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from fjord_ui import ConverterUI


def test_workspace_events_show_one_notice_and_update_it():
    messages=queue.Queue()
    for event in [('job_start',{'path':'movie.mkv','bitrate':30}),('job_status','Konverterer filmen'),
                  ('job_progress',(25,60,120)),('job_done',None),('job_error','Konvertering afbrudt')]:
        messages.put(event)
    app=SimpleNamespace(workspace_sync=SimpleNamespace(messages=messages,runner=None),notice=Mock(),
        status=Mock(),selected_path=Mock(),job_detail=Mock(),percent=Mock(),folder_status=Mock(),
        bar={'value':0},cancel_button={},after=Mock(),poll_workspace=Mock())
    ConverterUI.poll_workspace(app)
    app.notice.started.assert_called_once_with('movie.mkv',detail='30 Mbps · NVIDIA-GPU · HEVC/MKV')
    app.notice.update_status.assert_called_once_with('Konverterer filmen')
    app.notice.progress.assert_called_once_with(120,25)
    assert app.notice.finish.call_count==2
    app.notice.finish.assert_called_with('Konvertering afbrudt',failed=True)


@pytest.mark.skipif(os.name!='nt',reason='Native Windows popup and focus behavior')
def test_popup_slides_above_taskbar_without_stealing_focus(tmp_path):
    import ctypes
    import tkinter as tk
    from ctypes import wintypes
    from windows_background import Notice
    root=tk.Tk();root.withdraw()
    notice=Notice(root)
    user=ctypes.WinDLL('user32')
    user.GetForegroundWindow.restype=wintypes.HWND
    before=user.GetForegroundWindow()
    try:
        notice.started('Scary Movie 3 (2003).mkv',detail='30 Mbps · NVIDIA-GPU · HEVC/MKV')
        start=notice.window.winfo_y()
        root.after(420,root.quit);root.mainloop()
        rect=wintypes.RECT();user.SystemParametersInfoW(48,0,ctypes.byref(rect),0)
        assert notice.window.winfo_y()<start
        assert notice.window.winfo_y()+notice.window.winfo_height()==rect.bottom-18
        assert user.GetForegroundWindow()==before
        notice.update_status('Konverterer på NVIDIA-GPU')
        notice.progress(125,24)
        root.update()
        assert notice.eta.get()=='24 % · Ca. 2 min. 5 sek. tilbage'
        from PIL import ImageGrab
        win=notice.window
        ImageGrab.grab(bbox=(win.winfo_rootx(),win.winfo_rooty(),win.winfo_rootx()+win.winfo_width(),win.winfo_rooty()+win.winfo_height())).save(tmp_path/'notification.png')
        notice.finish('Filmen er klar i Bibliotek.')
        assert 'FÆRDIG' in notice.heading.get()
        notice.hide()
        assert notice.window is None and notice.slide_timer is None and notice.hide_timer is None
    finally:
        notice.hide();root.destroy()
