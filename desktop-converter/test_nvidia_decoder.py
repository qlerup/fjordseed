import importlib.machinery
import importlib.util
import io
from pathlib import Path
import subprocess
import threading
from unittest.mock import Mock

import pytest

import nvidia_decoder as decoder


@pytest.fixture(autouse=True)
def empty_capability_cache():
    decoder.capabilities.cache_clear()
    yield
    decoder.capabilities.cache_clear()


def test_hevc_reader_requires_matching_nvdec_bit_depth_and_caches_capabilities(tmp_path,monkeypatch):
    executable=tmp_path/'NVEncC.exe';executable.write_bytes(b'test')
    run=Mock(return_value=Mock(stdout='Encoder: 10bit depth yes\nNVDec features\n  H.265/HEVC: nv12, yv12, yv12(10bit)\n'))
    monkeypatch.setattr(decoder.subprocess,'run',run)
    assert decoder.select({'codec_name':'hevc','pix_fmt':'yuv420p10le'},executable)=='avhw'
    assert decoder.select({'codec_name':'hevc','pix_fmt':'yuv420p'},executable)=='avhw'
    run.assert_called_once()
    assert decoder.select({'codec_name':'h264','pix_fmt':'yuv420p10le'},executable)=='avsw'


def test_encoder_support_is_not_mistaken_for_decoder_support(tmp_path,monkeypatch):
    executable=tmp_path/'NVEncC.exe';executable.write_bytes(b'test')
    run=Mock(return_value=Mock(stdout='Codec: H.265/HEVC\n10bit depth yes\nNVDec features\n  H.265/HEVC: nv12, yv12\n'))
    monkeypatch.setattr(decoder.subprocess,'run',run)
    assert decoder.select({'codec_name':'hevc','pix_fmt':'yuv420p10le'},executable)=='avsw'


def test_failed_hardware_check_stops_before_the_conversion(tmp_path,monkeypatch):
    executable=tmp_path/'NVEncC.exe';executable.write_bytes(b'test')
    monkeypatch.setattr(decoder.subprocess,'run',Mock(side_effect=subprocess.CalledProcessError(1,'NVEncC')))
    with pytest.raises(ValueError,match='ikke startet'):
        decoder.select({'codec_name':'hevc','pix_fmt':'yuv420p10le'},executable)


def test_native_access_violation_is_logged_and_not_accepted_as_a_result(tmp_path,monkeypatch):
    path=Path(__file__).with_name('fjord_encode.pyw')
    loader=importlib.machinery.SourceFileLoader('fjord_crash_test',str(path))
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec);loader.exec_module(module)
    source=tmp_path/'source.mkv';source.write_bytes(b'original')
    executable=tmp_path/'tool.exe';executable.write_bytes(b'test')
    monkeypatch.setattr(module.core,'TOOLS',{'nvencc':executable})
    monkeypatch.setattr(module.core,'probe',Mock(return_value={'format':{'duration':'1'},'streams':[
        {'codec_type':'video','codec_name':'hevc','pix_fmt':'yuv420p10le','avg_frame_rate':'24/1'}]}))
    monkeypatch.setattr(decoder,'select',Mock(return_value='avhw'))
    process=Mock();process.stdout=io.StringIO('encoder progress\n');process.wait.return_value=-1073741819
    process.poll.return_value=-1073741819
    popen=Mock(return_value=process)
    monkeypatch.setattr(module.subprocess,'Popen',popen)
    monkeypatch.setattr(module.subprocess,'CREATE_NO_WINDOW',0,raising=False)
    with pytest.raises(RuntimeError,match='0xC0000005'):
        module.convert(source,tmp_path,30,Mock(),threading.Event(),target_name='result.mkv')
    assert popen.call_args.args[0][1]=='--avhw'
    assert '0xC0000005' in (tmp_path/'result.log').read_text(encoding='utf-8')
    assert source.read_bytes()==b'original'
    assert not (tmp_path/'result.mkv').exists()
