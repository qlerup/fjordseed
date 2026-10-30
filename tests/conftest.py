import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest
import json
import time


@pytest.fixture(autouse=True)
def isolated_credit_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr('green_credit.CONFIG', tmp_path/'qbit-credit')
    monkeypatch.setattr('green_credit.POLICIES', tmp_path/'green-policy.json')


@pytest.fixture(autouse=True)
def verified_seed_health(isolated_credit_ledger, tmp_path_factory, monkeypatch):
    import green_credit
    health_root = tmp_path_factory.mktemp('seed-health')
    vpn = health_root/'vpn-status.json'
    monkeypatch.setattr(green_credit, 'SEED_HEALTH', health_root/'seed-clock-status.json')
    monkeypatch.setattr(green_credit, 'VPN_STATUS', vpn)
    vpn.write_text(json.dumps({'healthy': True, 'checked_at': time.time(), 'relay_enabled': False}))
    green_credit.publish_seed_health(True, 'test-session')


@pytest.fixture(autouse=True)
def isolated_download_storage(tmp_path, monkeypatch):
    monkeypatch.setattr('download_storage.CONFIG', tmp_path/'qbit-storage')
    monkeypatch.setattr('download_storage.download_root', lambda: tmp_path/'downloads')
