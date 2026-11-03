import io
from unittest.mock import Mock

from app import create_app
from test_app import FakeRuntime, login


def setup(tmp_path):
    app = create_app(tmp_path, testing=True, runtime_factory=FakeRuntime)
    client, headers = login(app)
    return app, client, headers


def preview(client, headers):
    raw = b'd4:infod6:lengthi1e4:name15:Actual.Film.mkvee'
    return client.post('/api/torrents/preview', headers=headers,
                       data={'torrent': (io.BytesIO(raw), 'NordicBytes-171773.torrent')})


def test_internal_title_is_available_without_tracker_or_cover(tmp_path):
    app, client, headers = setup(tmp_path)
    app.extensions['trackers'].benefits.request = Mock(return_value={'status': 'unknown', 'matches': []})
    response = preview(client, headers)
    assert response.status_code == 200
    assert response.json['torrent'] == {'title': 'Actual.Film.mkv', 'cover': None, 'cover_pending': False}
    app.extensions['runtime'].rpc.assert_not_called()


def test_verified_title_and_cover_appear_as_cache_becomes_ready(tmp_path):
    app, client, headers = setup(tmp_path)
    poster = 'https://image.tmdb.org/t/p/w185/example.jpg'
    app.extensions['trackers'].benefits.request = Mock(return_value={'status': 'matched',
        'matches': [{'title': 'Actual Film (2026)', 'poster': poster}]})
    covers = app.extensions['covers']
    covers.request = Mock(side_effect=[None, '/api/covers/'+'a'*64])
    first = preview(client, headers).json['torrent']
    second = preview(client, headers).json['torrent']
    assert first == {'title': 'Actual Film (2026)', 'cover': None, 'cover_pending': True}
    assert second == {**first, 'cover': '/api/covers/'+'a'*64, 'cover_pending': False}
    covers.request.assert_called_with(poster)


def test_untrusted_cover_url_and_nonstring_tracker_title_are_ignored(tmp_path):
    app, client, headers = setup(tmp_path)
    app.extensions['trackers'].benefits.request = Mock(return_value={'status': 'matched',
        'matches': [{'title': [], 'poster': 'http://127.0.0.1/private'}]})
    assert preview(client, headers).json['torrent'] == {
        'title': 'Actual.Film.mkv', 'cover': None, 'cover_pending': False}
    assert app.extensions['covers'].jobs.empty()
