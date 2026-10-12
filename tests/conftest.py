import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pytest


@pytest.fixture(autouse=True)
def isolated_credit_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr('green_credit.CONFIG', tmp_path/'qbit-credit')
    monkeypatch.setattr('green_credit.POLICIES', tmp_path/'green-policy.json')


@pytest.fixture(autouse=True)
def isolated_download_storage(tmp_path, monkeypatch):
    monkeypatch.setattr('download_storage.CONFIG', tmp_path/'qbit-storage')
    monkeypatch.setattr('download_storage.download_root', lambda: tmp_path/'downloads')
