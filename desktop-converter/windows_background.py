"""Windows tray icon and non-activating notifications beside the clock."""
import ctypes
import queue
from ctypes import wintypes
from pathlib import Path
import tkinter as tk


class Notice:
    def __init__(self,root):
        self.root=root;self.window=None;self.hide_timer=None;self.slide_timer=None

    def started(self,name,title='Konvertering startet',detail=''):
        self.hide()
        win=tk.Toplevel(self.root);self.window=win
        win.title('Fjord · Konvertering startet')
        win.withdraw();win.overrideredirect(True);win.attributes('-topmost',True)
        win.configure(bg='#2d635e',padx=1,pady=1)
        panel=tk.Frame(win,bg='#122332',padx=17,pady=14);panel.pack(fill='both',expand=True)
        self.heading=tk.StringVar(value='FJORD  ·  '+title.upper())
        tk.Label(panel,textvariable=self.heading,bg='#122332',fg='#7ce4c4',font=('Segoe UI',9,'bold'),anchor='w').pack(fill='x')
        tk.Label(panel,text=name,bg='#122332',fg='#edf3fb',font=('Segoe UI',11,'bold'),wraplength=310,justify='left',anchor='w').pack(fill='x',pady=(8,5))
        if detail:tk.Label(panel,text=detail,bg='#122332',fg='#7ce4c4',font=('Segoe UI',9),anchor='w').pack(fill='x',pady=(0,5))
        self.status=tk.StringVar(value='Starter konvertering på NVIDIA-GPU …')
        tk.Label(panel,textvariable=self.status,bg='#122332',fg='#edf3fb',font=('Segoe UI',9),wraplength=310,justify='left',anchor='w',height=2).pack(fill='x')
        self.eta=tk.StringVar(value='Beregner resterende tid …')
        tk.Label(panel,textvariable=self.eta,bg='#122332',fg='#aebed5',font=('Segoe UI',10),anchor='w').pack(fill='x')
        win.update_idletasks()
        user=ctypes.WinDLL('user32',use_last_error=True)
        rect=wintypes.RECT();user.SystemParametersInfoW(48,0,ctypes.byref(rect),0)
        width=350;height=win.winfo_reqheight()
        x=rect.right-width-18;target=rect.bottom-height-18;start=rect.bottom
        win.geometry(f'{width}x{height}+{x}+{start}')
        win.update_idletasks()
        user.GetParent.argtypes=[wintypes.HWND];user.GetParent.restype=wintypes.HWND
        hwnd=user.GetParent(win.winfo_id()) or win.winfo_id()
        get=user.GetWindowLongPtrW;get.argtypes=[wintypes.HWND,ctypes.c_int];get.restype=ctypes.c_ssize_t
        put=user.SetWindowLongPtrW;put.argtypes=[wintypes.HWND,ctypes.c_int,ctypes.c_ssize_t];put.restype=ctypes.c_ssize_t
        put(hwnd,-20,get(hwnd,-20)|0x08000000|0x00000080)  # no activation, no taskbar entry
        # Tk's deiconify can recreate the wrapper and activate it, discarding
        # the no-activate style. Map the existing wrapper through Win32 instead.
        user.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int];user.ShowWindow(hwnd,4)
        win.bind('<Button-1>',lambda e:self.hide())
        for child in panel.winfo_children():child.bind('<Button-1>',lambda e:self.hide())
        def slide(frame=0):
            if self.window is not win:return
            fraction=min(1,frame/18)
            y=round(start+(target-start)*(1-(1-fraction)**3))
            win.geometry(f'{width}x{height}+{x}+{y}')
            self.slide_timer=self.root.after(16,lambda:slide(frame+1)) if frame<18 else None
        slide()
        self.hide_timer=self.root.after(18000,self.hide)

    def update_status(self,message):
        if self.window and self.window.winfo_exists():self.status.set(str(message)[:160])

    def phase(self,message):
        if self.window and self.window.winfo_exists():
            self.update_status(message)
            self.eta.set('')

    def progress(self,seconds,percent=None):
        if not self.window or not self.window.winfo_exists():return
        seconds=max(0,int(seconds))
        if seconds>=3600:text=f'{seconds//3600} t. {seconds//60%60} min.'
        elif seconds>=60:text=f'{seconds//60} min. {seconds%60} sek.'
        else:text=f'{seconds} sek.'
        self.eta.set((f'{percent:.0f} % · ' if percent is not None else '')+'Ca. '+text+' tilbage')

    def finish(self,message,failed=False):
        if not self.window or not self.window.winfo_exists():return
        self.heading.set('FJORD  ·  '+('KONVERTERING STOPPET' if failed else 'KONVERTERING FÆRDIG'))
        self.update_status(message);self.eta.set('Originalfilerne er bevaret.' if failed else '100 % · Færdig')
        if self.hide_timer:self.root.after_cancel(self.hide_timer)
        self.hide_timer=self.root.after(7000,self.hide)

    def hide(self):
        if self.slide_timer:
            self.root.after_cancel(self.slide_timer);self.slide_timer=None
        if self.hide_timer:
            self.root.after_cancel(self.hide_timer);self.hide_timer=None
        if self.window:
            self.window.destroy();self.window=None


class IconData(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('hwnd',wintypes.HWND),('ident',wintypes.UINT),
        ('flags',wintypes.UINT),('message',wintypes.UINT),('icon',wintypes.HICON),
        ('tip',wintypes.WCHAR*128),('state',wintypes.DWORD),('state_mask',wintypes.DWORD),
        ('info',wintypes.WCHAR*256),('version',wintypes.UINT),('title',wintypes.WCHAR*64),
        ('info_flags',wintypes.DWORD),('guid',ctypes.c_byte*16),('balloon_icon',wintypes.HICON)]


class Tray:
    MESSAGE=0x8000+42

    def __init__(self,root,icon,show,quit):
        self.root,self.show,self.quit=root,show,quit
        self.actions=queue.SimpleQueue()
        self.poll_timer=None
        self.user=ctypes.WinDLL('user32',use_last_error=True)
        self.shell=ctypes.WinDLL('shell32',use_last_error=True)
        self.comctl=ctypes.WinDLL('comctl32',use_last_error=True)
        ptr=ctypes.c_size_t;result=ctypes.c_ssize_t
        self.callback_type=ctypes.WINFUNCTYPE(result,wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM,ptr,ptr)
        self.callback=self.callback_type(self._message)
        self.user.GetParent.argtypes=[wintypes.HWND];self.user.GetParent.restype=wintypes.HWND
        self.user.LoadImageW.argtypes=[wintypes.HINSTANCE,wintypes.LPCWSTR,wintypes.UINT,ctypes.c_int,ctypes.c_int,wintypes.UINT]
        self.user.LoadImageW.restype=wintypes.HANDLE
        self.user.DestroyIcon.argtypes=[wintypes.HICON]
        self.user.RegisterWindowMessageW.argtypes=[wintypes.LPCWSTR];self.user.RegisterWindowMessageW.restype=wintypes.UINT
        self.recreated=self.user.RegisterWindowMessageW('TaskbarCreated')
        from windows_instance import wake_message
        self.wake=wake_message(root.root_dir)
        self.shell.Shell_NotifyIconW.argtypes=[wintypes.DWORD,ctypes.POINTER(IconData)];self.shell.Shell_NotifyIconW.restype=wintypes.BOOL
        self.comctl.SetWindowSubclass.argtypes=[wintypes.HWND,self.callback_type,ptr,ptr];self.comctl.SetWindowSubclass.restype=wintypes.BOOL
        self.comctl.RemoveWindowSubclass.argtypes=[wintypes.HWND,self.callback_type,ptr]
        self.comctl.DefSubclassProc.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM];self.comctl.DefSubclassProc.restype=result
        self.user.CreatePopupMenu.restype=wintypes.HMENU
        self.user.AppendMenuW.argtypes=[wintypes.HMENU,wintypes.UINT,ptr,wintypes.LPCWSTR]
        self.user.TrackPopupMenu.argtypes=[wintypes.HMENU,wintypes.UINT,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.HWND,ctypes.c_void_p]
        self.user.TrackPopupMenu.restype=wintypes.UINT
        self.user.DestroyMenu.argtypes=[wintypes.HMENU]
        self.user.SetForegroundWindow.argtypes=[wintypes.HWND]
        self.user.PostMessageW.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
        root.update_idletasks()
        self.hwnd=self.user.GetParent(root.winfo_id()) or root.winfo_id()
        self.icon=self.user.LoadImageW(None,str(Path(icon)),1,32,32,0x10)
        if not self.icon:raise ctypes.WinError(ctypes.get_last_error())
        self.data=IconData();self.data.size=ctypes.sizeof(IconData);self.data.hwnd=self.hwnd
        self.data.ident=1;self.data.flags=1|2|4;self.data.message=self.MESSAGE;self.data.icon=self.icon
        self.data.tip='Fjord-konvertering · kører i baggrunden'
        if not self.comctl.SetWindowSubclass(self.hwnd,self.callback,0xF10E,0):
            self.user.DestroyIcon(self.icon);raise ctypes.WinError(ctypes.get_last_error())
        if not self.shell.Shell_NotifyIconW(0,ctypes.byref(self.data)):
            self.comctl.RemoveWindowSubclass(self.hwnd,self.callback,0xF10E)
            self.user.DestroyIcon(self.icon);raise ctypes.WinError(ctypes.get_last_error())
        self.data.version=4;self.shell.Shell_NotifyIconW(4,ctypes.byref(self.data))
        self.closed=False
        root.bind('<Destroy>',self._destroy,add='+')
        self.poll_timer=root.after(50,self._dispatch)

    def _dispatch(self):
        """Only Tk's own event loop may call Tk; native callbacks just enqueue."""
        self.poll_timer=None
        try:
            while not self.closed:
                action=self.actions.get_nowait()
                if action=='show':self.show()
                elif action=='quit':self.quit()
        except queue.Empty:
            pass
        finally:
            if not self.closed:self.poll_timer=self.root.after(50,self._dispatch)

    def _message(self,hwnd,message,wparam,lparam,ident,reference):
        if message==self.wake:
            self.actions.put('show')
            return 0
        if message==self.recreated:
            self.shell.Shell_NotifyIconW(0,ctypes.byref(self.data))
            self.shell.Shell_NotifyIconW(4,ctypes.byref(self.data))
        elif message==self.MESSAGE:
            event=lparam&0xffff
            if event in (0x203,0x400,0x401):self.actions.put('show')
            elif event in (0x205,0x7B):
                point=wintypes.POINT();self.user.GetCursorPos(ctypes.byref(point))
                menu=self.user.CreatePopupMenu()
                self.user.AppendMenuW(menu,0,1,'Åbn Fjord-konvertering')
                self.user.AppendMenuW(menu,0,2,'Afslut')
                self.user.SetForegroundWindow(hwnd)
                selected=self.user.TrackPopupMenu(menu,0x100|0x2,point.x,point.y,0,hwnd,None)
                self.user.DestroyMenu(menu);self.user.PostMessageW(hwnd,0,0,0)
                if selected:self.actions.put('show' if selected==1 else 'quit')
            return 0
        return self.comctl.DefSubclassProc(hwnd,message,wparam,lparam)

    def _destroy(self,event):
        if event.widget is self.root and not self.closed:
            self.closed=True
            if self.poll_timer:
                self.root.after_cancel(self.poll_timer);self.poll_timer=None
            self.shell.Shell_NotifyIconW(2,ctypes.byref(self.data))
            self.comctl.RemoveWindowSubclass(self.hwnd,self.callback,0xF10E)
            self.user.DestroyIcon(self.icon)
