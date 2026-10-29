import os
import queue
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from fjord_ui import ConverterUI


class ProgressBar(dict):
    def __init__(self):
        super().__init__(value=0,mode='determinate')
        self.start=Mock();self.stop=Mock()


def test_workspace_events_show_one_notice_and_update_it():
    messages=queue.Queue()
    for event in [('job_start',{'path':'movie.mkv','bitrate':30}),('job_status','Konverterer filmen'),
                  ('job_progress',(25,60,120)),('job_done',None),('job_error','Konvertering afbrudt')]:
        messages.put(event)
    app=SimpleNamespace(workspace_sync=SimpleNamespace(messages=messages,runner=None),notice=Mock(),
        status=Mock(),selected_path=Mock(),job_detail=Mock(),percent=Mock(),folder_status=Mock(),
        bar=ProgressBar(),cancel_button={},after=Mock(),poll_workspace=Mock())
    ConverterUI.poll_workspace(app)
    app.notice.started.assert_called_once_with('movie.mkv',detail='30 Mbps · NVIDIA-GPU · HEVC/MKV')
    app.notice.update_status.assert_called_once_with('Konverterer filmen')
    app.notice.progress.assert_called_once_with(120,25)
    assert app.notice.finish.call_count==2
    app.notice.finish.assert_called_with('Konvertering afbrudt',failed=True)


def test_post_encode_phase_clears_stale_fps_and_eta():
    messages=queue.Queue()
    messages.put(('job_progress',(99,49.3,0)))
    messages.put(('job_phase',{'stage':'source_verifying','detail':'Kontrollerer indholdet','phase_progress':42}))
    app=SimpleNamespace(workspace_sync=SimpleNamespace(messages=messages,runner=None),notice=Mock(),
        status=Mock(),selected_path=Mock(),job_detail=Mock(),percent=Mock(),folder_status=Mock(),
        bar=ProgressBar(),cancel_button={},after=Mock(),poll_workspace=Mock())
    ConverterUI.poll_workspace(app)
    app.notice.phase.assert_called_once_with('Kontrollerer indholdet')
    assert 'billeder/s' not in app.job_detail.set.call_args.args[0]
    assert app.bar['value']==42


def test_phase_without_visible_popup_is_safe():
    from windows_background import Notice
    Notice(Mock()).phase('Kontrollerer indholdet')


def test_each_phase_resets_bar_and_unknown_phases_animate():
    from fjord_ui import show_phase
    app=SimpleNamespace(bar=ProgressBar(),percent=Mock())
    show_phase(app,'encoding',99)
    show_phase(app,'metadata')
    assert app.bar['mode']=='indeterminate' and app.bar['value']==0
    assert app.bar.start.call_count==1
    started=app.phase_started
    show_phase(app,'metadata')
    assert app.phase_started==started and app.bar.start.call_count==1
    show_phase(app,'verifying')
    assert app.bar.start.call_count==2
    show_phase(app,'moving',12)
    assert app.bar['mode']=='determinate' and app.bar['value']==12
    show_phase(app,'completed',100)
    assert app.bar['value']==100 and app.bar['mode']=='determinate'


@pytest.mark.skipif(os.name!='nt',reason='Native Windows progress animation')
def test_native_bar_animates_between_measured_phases():
    import tkinter as tk
    from tkinter import ttk
    from fjord_ui import show_phase
    root=tk.Tk();root.withdraw()
    try:
        app=SimpleNamespace(bar=ttk.Progressbar(root,maximum=100),percent=tk.StringVar(root))
        show_phase(app,'encoding',99)
        show_phase(app,'metadata')
        root.after(150,root.quit);root.mainloop()
        assert str(app.bar['mode'])=='indeterminate' and float(app.bar['value'])>0
        show_phase(app,'verifying')
        assert 0<=float(app.bar['value'])<=1  # ttk starts with its first animation tick.
        root.after(100,root.quit);root.mainloop()
        assert float(app.bar['value'])>0
        show_phase(app,'moving',12)
        root.after(100,root.quit);root.mainloop()
        assert float(app.bar['value'])==12 and str(app.bar['mode'])=='determinate'
    finally:root.destroy()


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
    user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT]
    user.GetAncestor.restype=wintypes.HWND
    try:
        notice.started('Scary Movie 3 (2003).mkv',detail='30 Mbps · NVIDIA-GPU · HEVC/MKV')
        start=notice.window.winfo_y()
        root.after(420,root.quit);root.mainloop()
        rect=wintypes.RECT();user.SystemParametersInfoW(48,0,ctypes.byref(rect),0)
        assert notice.window.winfo_y()<start
        assert notice.window.winfo_y()+notice.window.winfo_height()==rect.bottom-18
        # The user may switch apps while the test runs; neither Tk window may
        # become foreground as a result of showing this notification.
        assert user.GetForegroundWindow() not in {
            user.GetAncestor(notice.window.winfo_id(),2),user.GetAncestor(root.winfo_id(),2)}
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
