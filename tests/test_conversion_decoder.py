"""GPU decoding follows the actual codec and bit-depth capabilities."""
from unittest.mock import Mock
import subprocess

import pytest

import conversion_decoder as decoder
from conversion_media import command


@pytest.fixture
def hardware(tmp_path, monkeypatch):
    decoder.capabilities.cache_clear()
    executable = tmp_path / 'nvencc'
    executable.write_bytes(b'test')
    run = Mock(return_value=Mock(stdout='NVEnc features\nCodec: H.265/HEVC\n'
        '10bit depth yes\nNVDec features\n'
        + ''.join(f'  {label}: nv12, yv12, yv12(10bit)\n' for label in decoder.CODECS.values())))
    monkeypatch.setattr(decoder.subprocess, 'run', run)
    yield executable, run
    decoder.capabilities.cache_clear()


@pytest.mark.parametrize('codec', list(decoder.CODECS))
@pytest.mark.parametrize('pixel', ['yuv420p', 'yuv420p10le'])
def test_supported_input_uses_gpu_decoding_and_hevc_gpu_encoding(hardware, codec, pixel):
    executable, run = hardware
    stream = {'codec_type': 'video', 'codec_name': codec, 'pix_fmt': pixel}
    reader = decoder.select(stream, executable)
    assert reader == 'avhw'
    args = command('input.mkv', 'output.mkv', 20, {'streams': [stream]}, reader=reader)
    assert args[:2] == ['nvencc', '--avhw']
    assert args[args.index('-c') + 1] == 'hevc'


def test_codec_and_bit_depth_must_both_match(hardware):
    executable, run = hardware
    run.return_value.stdout = ('Codec: H.264/AVC\n10bit depth yes\nNVDec features\n'
        '  H.264/AVC: nv12, yv12\n  H.265/HEVC: nv12, yv12, yv12(10bit)\n')
    assert decoder.select({'codec_name': 'h264', 'pix_fmt': 'yuv420p'}, executable) == 'avhw'
    assert decoder.select({'codec_name': 'h264', 'pix_fmt': 'yuv420p10le'}, executable) == 'avsw'
    assert decoder.select({'codec_name': 'av1', 'pix_fmt': 'yuv420p'}, executable) == 'avsw'
    run.assert_called_once()


def test_software_reader_still_uses_gpu_encoder(hardware):
    executable, run = hardware
    stream = {'codec_type': 'video', 'codec_name': 'ffv1', 'pix_fmt': 'yuv420p'}
    reader = decoder.select(stream, executable)
    assert reader == 'avsw'
    run.assert_not_called()
    assert command('in.mkv', 'out.mkv', 20, {'streams': [stream]}, reader=reader)[:2] == ['nvencc', '--avsw']


def test_failed_capability_probe_does_not_silently_start(hardware):
    executable, run = hardware
    run.side_effect = subprocess.CalledProcessError(1, 'nvencc')
    with pytest.raises(ValueError, match='ikke startet'):
        decoder.select({'codec_name': 'h264', 'pix_fmt': 'yuv420p'}, executable)


def test_queues_and_library_share_extended_video_formats():
    import conversion
    import converter_worker
    import library_conversion
    from conversion_media import VIDEO
    assert conversion.VIDEO is converter_worker.VIDEO is library_conversion.VIDEO is VIDEO
    assert {'.mpeg', '.mpg', '.mts', '.wmv', '.flv', '.ogv'} <= VIDEO
    assert '.iso' not in VIDEO and '.mp3' not in VIDEO
