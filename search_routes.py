"""Authenticated, session-owned search jobs with bounded lifetime."""
import secrets
import threading
import time

from flask import Blueprint, jsonify, request, session


def register(app, state, runtime):
    bp = Blueprint('torrent_search', __name__, url_prefix='/api/search')
    jobs, lock = {}, threading.RLock()

    def rpc(action, data):
        with state.lock:
            if not state.get()['enabled']:
                raise ValueError('Start seedboxen med en aktiv VPN først.')
            return runtime.rpc(action, data)

    @bp.errorhandler(ValueError)
    def invalid(exc):
        return jsonify(error=str(exc)), 409

    @bp.errorhandler(Exception)
    def unavailable(exc):
        app.logger.warning('Torrent search unavailable: %s', type(exc).__name__)
        return jsonify(error='Søgning er ikke tilgængelig. Kontrollér VPN og søgemaskiner.'), 503

    def body():
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError('Ugyldig søgeanmodning.')
        return data

    def public(result):
        return {k: v for k, v in result.items() if k != '_search_session'}

    def job_data(job, **extra):
        return {'id': job['id'], **({'_search_session': job['session']} if job.get('session') else {}), **extra}

    @bp.get('/plugins')
    def plugins():
        return jsonify(public(rpc('search-plugins', {})))

    @bp.post('/plugins')
    def install():
        return jsonify(public(rpc('search-install', {'name': body().get('name')})))

    @bp.post('')
    def start():
        data = body()
        owner = session.setdefault('search_owner', secrets.token_hex(16))
        with lock:
            # One job per browser session; old searches must not consume the
            # native five-search limit or leak results to another session.
            for token, job in list(jobs.items()):
                if job['owner'] == owner or time.monotonic() - job['created'] > 600:
                    rpc('search-delete', job_data(job))
                    del jobs[token]
            if len(jobs) >= 5:
                raise ValueError('Der er allerede fem søgninger. Prøv igen om lidt.')
            result = rpc('search-start', {'pattern': data.get('pattern'), 'plugin': data.get('plugin', 'enabled')})
            token = secrets.token_hex(16)
            jobs[token] = {'id': result['id'], 'owner': owner, 'created': time.monotonic(),
                           'session': result.get('_search_session', {})}
        return jsonify(token=token)

    @bp.route('/<token>', methods=['GET', 'POST'])
    def job_action(token):
        with lock:
            job = jobs.get(token)
            if not job or job['owner'] != session.get('search_owner'):
                return jsonify(error='Søgningen findes ikke. Start en ny søgning.'), 404
            data = body() if request.method == 'POST' else {}
            action = data.get('action', 'results')
            if action not in ('results', 'stop', 'resolve', 'delete') or (request.method == 'GET' and action != 'results'):
                raise ValueError('Ugyldig søgehandling.')
            try:
                offset = int(request.args.get('offset', 0)) if request.method == 'GET' else data.get('offset', 0)
            except ValueError:
                raise ValueError('Ugyldig side.') from None
            if time.monotonic() - job['created'] > 600 and action != 'delete':
                rpc('search-delete', job_data(job))
                del jobs[token]
                raise ValueError('Søgningen er udløbet. Søg igen.')
            result = rpc('search-' + action, job_data(job, offset=offset))
            if result.get('_search_session'):
                job['session'] = result['_search_session']
            if action == 'delete':
                del jobs[token]
            return jsonify(public(result))

    app.register_blueprint(bp)
