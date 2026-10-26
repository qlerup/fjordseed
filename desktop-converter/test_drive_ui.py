import json
from types import SimpleNamespace

import pytest

from fjord_ui import ConverterUI, read_settings, save_media_folder


def test_folder_selection_preserves_existing_preferences(tmp_path):
    path = tmp_path / 'preferences.json'
    folder = tmp_path / 'Media'
    folder.mkdir()
    path.write_text(json.dumps({'bitrate': 30, 'folder': 'old-output', 'drive': 'M:\\'}))
    assert save_media_folder(path, str(folder)) == str(folder)
    assert read_settings(path) == {'bitrate': 30, 'folder': 'old-output', 'drive': 'M:\\', 'media_folder': str(folder)}


def test_invalid_folder_is_not_saved(tmp_path):
    path = tmp_path / 'preferences.json'
    path.write_text('{}')
    with pytest.raises(ValueError):
        save_media_folder(path, str(tmp_path / 'missing'))
    assert read_settings(path) == {}


def test_cancelled_folder_picker_keeps_previous_selection(tmp_path, monkeypatch):
    from unittest.mock import Mock
    import fjord_ui
    picker = Mock(return_value='')
    monkeypatch.setattr(fjord_ui.filedialog, 'askdirectory', picker)
    app = SimpleNamespace(media_folder=Mock(), config_path=tmp_path/'preferences.json', folder_status=Mock(),workspace_sync=SimpleNamespace(runner=None))
    app.media_folder.get.return_value=str(tmp_path)
    ConverterUI.choose_folder(app)
    app.media_folder.set.assert_not_called()
    assert not app.config_path.exists()
    assert picker.call_args.kwargs['mustexist'] is True


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
