import sys
from types import SimpleNamespace

import windows_startup as startup


def test_startup_toggle_only_changes_own_current_user_entry(tmp_path,monkeypatch):
    values={'OtherApp':'leave me alone'}
    class Key:
        def __enter__(self):return self
        def __exit__(self,*a):pass
    def get(key,name):
        if name not in values:raise FileNotFoundError()
        return values[name],1
    def delete(key,name):
        if name not in values:raise FileNotFoundError()
        del values[name]
    registry=SimpleNamespace(HKEY_CURRENT_USER='current-user',REG_SZ=1,KEY_SET_VALUE=2,
        OpenKey=lambda *a:Key(),CreateKeyEx=lambda *a:Key(),QueryValueEx=get,
        SetValueEx=lambda key,name,reserved,kind,value:values.__setitem__(name,value),DeleteValue=delete)
    monkeypatch.setitem(sys.modules,'winreg',registry)
    monkeypatch.setattr(startup,'os',SimpleNamespace(name='nt'))
    script=tmp_path/'folder with spaces'/'fjord_encode.pyw'
    assert not startup.enabled(script)
    startup.configure(script,True)
    assert startup.enabled(script)
    assert '--background' in values[startup.NAME] and 'pythonw.exe' in values[startup.NAME]
    startup.configure(script,False)
    assert not startup.enabled(script)
    assert values=={'OtherApp':'leave me alone'}
