import threading

from trackers import Trackers


HASH = 'a' * 40


def test_rss_admission_and_saved_status_do_not_deadlock(tmp_path):
    trackers = Trackers(tmp_path)
    benefits = trackers.benefits
    saved = {'status': 'matched', 'matches': []}
    meta = {'hashes': [HASH], 'name': 'fixture'}
    benefits.snapshots[HASH] = saved
    underlying = trackers.lock
    feed_has_tracker = threading.Event()
    status_wants_tracker = threading.Event()
    errors = []

    class ObservedLock:
        def __enter__(self):
            if threading.current_thread().name == 'status-reader':
                status_wants_tracker.set()
            underlying.acquire()
            return self

        def __exit__(self, *_):
            underlying.release()

    trackers.lock = ObservedLock()

    def admit_feed():
        try:
            with trackers.lock:
                feed_has_tracker.set()
                assert status_wants_tracker.wait(2)
                # Same tracker -> benefit order used by RssGate.tick.
                benefits.remember(meta, saved)
        except BaseException as exc:
            errors.append(exc)

    def read_status():
        try:
            assert feed_has_tracker.wait(2)
            assert benefits.snapshot(meta)['status'] == 'matched'
        except BaseException as exc:
            errors.append(exc)

    feed = threading.Thread(target=admit_feed, daemon=True)
    reader = threading.Thread(target=read_status, name='status-reader', daemon=True)
    feed.start()
    reader.start()
    feed.join(3)
    reader.join(3)
    assert not feed.is_alive() and not reader.is_alive(), 'RSS admission and status deadlocked'
    assert not errors


def test_cached_request_never_acquires_tracker_after_benefit_lock(tmp_path):
    trackers = Trackers(tmp_path)
    trackers.save({'provider': 'nordicbytes', 'name': 'fixture', 'api_key': 'fixture-not-real-key'})
    benefits = trackers.benefits
    meta = {'hashes': [HASH], 'name': 'fixture'}
    benefits.request(meta)
    underlying = trackers.lock

    class OrderedLock:
        def __enter__(self):
            assert underlying._is_owned() or not benefits.lock._is_owned(), 'benefit -> tracker inversion'
            underlying.acquire()
            return self

        def __exit__(self, *_):
            underlying.release()

    trackers.lock = OrderedLock()
    assert benefits.request(meta)['status'] == 'pending'
