import threading
from unittest.mock import Mock
from trackers import Trackers

HASH = 'a' * 40
META = {'hashes': [HASH], 'name': 'Test release'}
RESULT = {'status': 'matched', 'matches': [{'tracker_id': 'fixture', 'freeleech': 100}]}


def test_saved_display_survives_restart_and_does_not_request_again(tmp_path):
    benefits = Trackers(tmp_path).benefits
    benefits.request = Mock(return_value=RESULT)
    assert benefits.snapshot(META) == RESULT
    benefits.request.assert_called_once()
    benefits.snapshot(META)['matches'][0]['freeleech'] = 0
    restored = Trackers(tmp_path).benefits
    restored.request = Mock(side_effect=AssertionError('No live lookup for saved display'))
    assert restored.snapshot(META) == RESULT
    assert (tmp_path / 'torrent-benefits.json').exists()


def test_missing_metadata_is_not_frozen(tmp_path):
    benefits = Trackers(tmp_path).benefits
    benefits.request = Mock(return_value=RESULT)
    assert benefits.snapshot({'hashes': [HASH], 'name': ''})['status'] == 'unknown'
    benefits.request.assert_not_called()
    assert benefits.snapshot(META) == RESULT


def test_async_display_job_is_saved_without_another_poll(tmp_path):
    trackers = Trackers(tmp_path)
    trackers.save({'provider': 'nordicbytes', 'name': 'Tracker', 'api_key': 'fixture-not-real-key'})
    benefits = trackers.benefits
    stop = threading.Event()
    def lookup(*args):
        stop.set()
        return RESULT
    benefits.lookup = Mock(side_effect=lookup)
    assert benefits.snapshot(META)['status'] == 'pending'
    benefits.run(stop)
    restored = Trackers(tmp_path).benefits
    restored.request = Mock(side_effect=AssertionError('Should use saved data'))
    assert restored.snapshot(META) == RESULT


def test_rss_live_request_does_not_use_frozen_display(tmp_path):
    trackers = Trackers(tmp_path)
    trackers.save({'provider': 'nordicbytes', 'name': 'Tracker', 'api_key': 'fixture-not-real-key'})
    benefits = trackers.benefits
    benefits.remember(META, RESULT)
    assert benefits.request(META, max_age=30)['status'] == 'pending'
    assert benefits.jobs.qsize() == 1
    assert benefits.snapshot(META) == RESULT
