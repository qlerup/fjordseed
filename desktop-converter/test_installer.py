import hashlib

import pytest

from build_installer import archive_for, validate_payload, validate_version


@pytest.mark.parametrize('version', ['0.5.7', '1.20.300'])
def test_installer_accepts_numeric_release_versions(version):
    validate_version(version)


@pytest.mark.parametrize('version', ['0.5', 'v0.5.7', '0.5.7\n', '0.5.7;echo unexpected'])
def test_installer_rejects_invalid_release_versions(version):
    with pytest.raises(ValueError, match='three-part numeric'):
        validate_version(version)


def test_changed_cached_vendor_archive_is_not_executed_or_accepted(tmp_path):
    (tmp_path / 'tool.7z').write_bytes(b'changed archive')
    tool = {'file': 'tool.7z', 'sha256': hashlib.sha256(b'official archive').hexdigest(),
            'url': 'https://example.invalid/never-requested'}
    with pytest.raises(ValueError, match='Checksum mismatch'):
        archive_for(tool, tmp_path)


def test_installer_rejects_personal_pairing_preferences_in_payload(tmp_path):
    for name in ('Fjord-konvertering.exe', 'fjord.ico', 'NVEncC64.exe',
                 'ffmpeg/bin/ffprobe.exe', 'ffmpeg/bin/ffmpeg.exe', 'mkvtoolnix/mkvpropedit.exe'):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture')
    validate_payload(tmp_path)
    (tmp_path / 'worker-settings.json').write_text('{"token_dpapi":"private"}')
    with pytest.raises(ValueError, match='User settings'):
        validate_payload(tmp_path)
