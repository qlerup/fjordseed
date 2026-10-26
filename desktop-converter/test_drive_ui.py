import json
from types import SimpleNamespace

import pytest

from fjord_ui import ConverterUI, read_settings, save_drive


def test_drive_selection_preserves_existing_preferences(tmp_path):
    path = tmp_path / 'preferences.json'
    path.write_text(json.dumps({'bitrate': 30, 'folder': 'old-output'}))
    assert save_drive(path, 'm:\\') == 'M:\\'
    assert read_settings(path) == {'bitrate': 30, 'folder': 'old-output', 'drive': 'M:\\'}


@pytest.mark.parametrize('drive', ['', 'M:', 'M:\\Downloads', '../files', '\\\\server\\share'])
def test_only_selected_drive_roots_are_saved(tmp_path, drive):
    path = tmp_path / 'preferences.json'
    path.write_text('{"drive":"M:\\\\"}')
    before = path.read_bytes()
    with pytest.raises(ValueError):
        save_drive(path, drive)
    assert path.read_bytes() == before


def test_saving_new_pairing_code_preserves_connection_options_and_encrypts_token(tmp_path, monkeypatch):
    import base64
    import windows_secret
    path = tmp_path / 'worker-settings.json'
    path.write_text(json.dumps({'server': 'http://old.test', 'cache': 'old-cache', 'auto': True}))
    token = 'fsw_' + 'a' * 48
    code = 'fsp1_' + base64.urlsafe_b64encode(json.dumps({'server': 'http://seed.test', 'token': token}).encode()).decode().rstrip('=')
    monkeypatch.setattr(windows_secret, 'protect', lambda value: 'encrypted' if value == token else 'wrong')
    ConverterUI.save_connection(SimpleNamespace(connection_path=path), code)
    saved = read_settings(path)
    assert saved == {'server': 'http://seed.test', 'cache': 'old-cache', 'auto': True, 'token_dpapi': 'encrypted'}
    assert token not in path.read_text()
    before = path.read_bytes()
    ConverterUI.save_connection(SimpleNamespace(connection_path=path), '')
    assert path.read_bytes() == before
