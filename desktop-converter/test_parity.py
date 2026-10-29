"""Desktop and server must call the same encoding policy and preservation checks."""
import copy
from pathlib import Path
from unittest.mock import Mock

import pytest
import encode_core as desktop
import converter_worker as server
import conversion_media as shared
import conversion_decoder
import nvidia_decoder


@pytest.mark.parametrize('name',['command','video','dovi','validate'])
def test_desktop_server_use_same_functions(name):
    assert getattr(desktop,name) is getattr(shared,name)
    assert getattr(server,name) is getattr(shared,name)


def test_desktop_server_share_decoder_selection():
    assert nvidia_decoder.select is conversion_decoder.select
    assert server.select_decoder is conversion_decoder.select


def test_windows_probe_uses_shared_probe_with_windows_tools(monkeypatch):
    call=Mock(return_value={'streams':[]})
    monkeypatch.setattr(desktop,'_probe',call)
    assert desktop.probe(Path('film.mkv'))=={'streams':[]}
    call.assert_called_once_with(Path('film.mkv'),run=desktop.subprocess.run)


def test_windows_metadata_restoration_uses_shared_policy(monkeypatch):
    call=Mock();monkeypatch.setattr(desktop,'_restore_flags',call)
    desktop.restore_flags({'streams':[]},Path('film.mkv'))
    call.assert_called_once_with({'streams':[]},Path('film.mkv'),run=desktop.subprocess.run)
