"""Authenticated track merge API and background RPC driver."""
import logging
import threading
from flask import jsonify, request, session


def register(app, runtime, stop, testing=False):
    def call(action, data=None):
        payload = {**(data or {}), 'owner': 'hub:'+str(session['hub_uid']) if 'hub_uid' in session else 'local'}
        try: return jsonify(runtime.rpc('library-merge-'+action, payload))
        except ValueError as exc: return jsonify(error=str(exc)), 400

    @app.get('/api/merge/library')
    def merge_library(): return call('list')

    @app.get('/api/merge/library/<ident>')
    def merge_details(ident): return call('details', {'id': ident})

    @app.get('/api/merge/jobs')
    def merge_jobs(): return call('jobs')

    @app.post('/api/merge/queue')
    def merge_queue():
        data = request.get_json(silent=True)
        if not isinstance(data, dict): return jsonify(error='Forventede et JSON-objekt.'), 400
        return call('queue', data)

    @app.post('/api/merge/jobs/<ident>/<action>')
    def merge_action(ident, action):
        if action not in ('cancel', 'retry'): return jsonify(error='Ukendt flettehandling.'), 400
        return call(action, {'id': ident})

    def run():
        while not stop.wait(3):
            try: runtime.rpc('library-merge-tick', {})
            except ValueError: pass  # VPN/qBittorrent can be intentionally stopped.
            except Exception: logging.getLogger(__name__).exception('Track merge worker failed')

    if not testing: threading.Thread(target=run, name='track-merges', daemon=True).start()
