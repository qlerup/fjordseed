"""Windows Explorer file drops for a Tk window, without extra packages."""
import ctypes
from ctypes import wintypes


class FileDrop:
    WM_DROPFILES = 0x0233
    WM_NCDESTROY = 0x0082

    def __init__(self, root, receive):
        self.root, self.receive = root, receive
        self.handles = []
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.shell = ctypes.WinDLL('shell32', use_last_error=True)
        self.comctl = ctypes.WinDLL('comctl32', use_last_error=True)
        pointer = ctypes.c_size_t
        result = ctypes.c_ssize_t
        self.callback_type = ctypes.WINFUNCTYPE(result, wintypes.HWND, wintypes.UINT,
                                               wintypes.WPARAM, wintypes.LPARAM, pointer, pointer)
        self.callback = self.callback_type(self._message)
        self.user.GetParent.argtypes = [wintypes.HWND]
        self.user.GetParent.restype = wintypes.HWND
        self.shell.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
        self.shell.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
        self.shell.DragQueryFileW.restype = wintypes.UINT
        self.shell.DragFinish.argtypes = [wintypes.HANDLE]
        self.comctl.SetWindowSubclass.argtypes = [wintypes.HWND, self.callback_type, pointer, pointer]
        self.comctl.SetWindowSubclass.restype = wintypes.BOOL
        self.comctl.RemoveWindowSubclass.argtypes = [wintypes.HWND, self.callback_type, pointer]
        self.comctl.DefSubclassProc.argtypes = [wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM]
        self.comctl.DefSubclassProc.restype = result
        root.update_idletasks()
        client = root.winfo_id()
        try:
            for handle in dict.fromkeys((client, self.user.GetParent(client))):
                if handle:
                    if not self.comctl.SetWindowSubclass(handle, self.callback, 0xF10D, 0):
                        raise ctypes.WinError(ctypes.get_last_error())
                    self.handles.append(handle)
                    self.shell.DragAcceptFiles(handle, True)
        except Exception:
            self.close()
            raise
        root.bind('<Destroy>', self._destroy, add='+')

    def _message(self, hwnd, message, wparam, lparam, ident, reference):
        if message == self.WM_DROPFILES:
            try:
                count = self.shell.DragQueryFileW(wparam, 0xFFFFFFFF, None, 0)
                paths = []
                # One file is supported; retain a second path to reject multi-drop.
                for index in range(min(count, 2)):
                    length = self.shell.DragQueryFileW(wparam, index, None, 0)
                    buffer = ctypes.create_unicode_buffer(length + 1)
                    self.shell.DragQueryFileW(wparam, index, buffer, length + 1)
                    paths.append(buffer.value)
                self.receive(paths)
            finally:
                self.shell.DragFinish(wparam)
            return 0
        if message == self.WM_NCDESTROY:
            self.comctl.RemoveWindowSubclass(hwnd, self.callback, 0xF10D)
        return self.comctl.DefSubclassProc(hwnd, message, wparam, lparam)

    def _destroy(self, event):
        if event.widget is self.root:
            self.close()

    def close(self):
        for handle in self.handles:
            self.shell.DragAcceptFiles(handle, False)
            self.comctl.RemoveWindowSubclass(handle, self.callback, 0xF10D)
        self.handles.clear()
