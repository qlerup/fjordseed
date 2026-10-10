import base64
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import signal
import threading
import time

from flask import Flask, jsonify, redirect, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from hub import Hub, HubError
from runtime import Runtime
from qbit_rpc import share_policy
from trackers import Trackers
from torrent_meta import torrent_meta, magnet_meta
from rss import Rss,write_snapshot
from rss_gate import RssGate
from benefits import ratio_estimate
from state import State, atomic


def create_app(root=None, testing=False, runtime_factory=Runtime):
    state = State(root or os.environ.get('FJORDSEED_DATA','/data'))
    hub = Hub()
    app = Flask(__name__)
    app.config.update(SECRET_KEY=state.secret_path.read_text(), TESTING=testing,
        MAX_CONTENT_LENGTH=4*1024*1024, SESSION_COOKIE_NAME='fjordseed_session',
        SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', PERMANENT_SESSION_LIFETIME=28800)
    auth_path = state.root/'auth.json'
    if not hub.enabled and not auth_path.exists():
        password = secrets.token_urlsafe(20)
        atomic(auth_path, json.dumps({'password_hash':generate_password_hash(password)}))
        atomic(state.root/'initial-login.txt', password + '\n')
    runtime = runtime_factory(state)
    stop = threading.Event()
    trackers = Trackers(state.root)
    trackers.benefits.publish_green()
    rss = Rss(state.root)
    rss_gate = RssGate(rss,runtime,state,trackers.benefits)
    app.extensions.update(state=state, runtime=runtime, stop=stop, hub=hub, trackers=trackers, rss=rss)
    failures, auth_lock = {}, threading.Lock()
    allowed_hosts = {'localhost','127.0.0.1'} | set(filter(None, os.environ.get('UI_ALLOWED_HOSTS','').split(',')))

    @app.before_request
    def guard():
        hostname = request.host.split(':')[0]
        if hostname not in allowed_hosts:
            try:
                address = ipaddress.ip_address(hostname)
                allowed = not os.environ.get('UI_ALLOWED_HOSTS') and any(address in ipaddress.ip_network(n)
                    for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16'))
            except ValueError:
                allowed = False
            if not allowed:
                return jsonify(error='Ukendt værtsnavn.'), 403
        if request.method == 'POST':
            expected = session.get('csrf','')
            actual = request.headers.get('X-CSRF-Token') or request.form.get('csrf','')
            if not expected or not secrets.compare_digest(expected, actual):
                return jsonify(error='Genindlæs siden og prøv igen.'),403
        if request.endpoint in ('login','hub_login','static','health','logout'):
            return
        if session.get('authenticated') and hub.enabled:
            try:
                hub.current(session.get('hub_uid'))
            except HubError as exc:
                if exc.status != 503:
                    session.clear()
                    session['hub_access_revoked'] = True
                return jsonify(error=str(exc), error_code='access_revoked' if exc.status != 503 else 'hub_unavailable'), exc.status
        if not session.get('authenticated'):
            if request.path.startswith('/api/'):
                return jsonify(error='Log ind for at fortsætte.', authenticated=False),401
            return redirect('/login')

    @app.after_request
    def headers(response):
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
            'X-Frame-Options':'DENY','Referrer-Policy':'same-origin',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"})
        return response

    @app.errorhandler(413)
    def too_large(_):
        return jsonify(error='Torrentfilen er for stor. Maksimum er 4 MB.'),413

    def authenticate(user=None):
        session.clear()
        session.update(authenticated=True, csrf=secrets.token_urlsafe(32))
        if user:
            session['hub_uid'] = user['id']
        session.permanent = True
        return redirect('/')

    @app.route('/login',methods=['GET','POST'])
    def login():
        session.setdefault('csrf', secrets.token_urlsafe(32))
        error = ''
        if request.method == 'POST':
            with auth_lock:
                address = request.remote_addr
                recent = [t for t in failures.get(address,[]) if time.time()-t < 300]
                failures[address] = recent
                if len(recent) >= 5:
                    return render_template('login.html', error='Vent fem minutter før næste forsøg.', managed=hub.enabled),429
                try:
                    if hub.enabled:
                        user = hub.authenticate(request.form.get('username',''), request.form.get('password',''))
                    else:
                        auth = json.loads(auth_path.read_text())
                        if request.form.get('username') != 'admin' or not check_password_hash(auth['password_hash'], request.form.get('password','')):
                            raise ValueError('Forkert brugernavn eller adgangskode.')
                        user = None
                    failures.pop(address, None)
                    return authenticate(user)
                except (HubError, ValueError) as exc:
                    recent.append(time.time())
                    error = str(exc)
        return render_template('login.html', error=error, managed=hub.enabled)

    @app.get('/hub-login')
    def hub_login():
        if not hub.enabled:
            return redirect('/login')
        try:
            return authenticate(hub.sso(request.args.get('token','')))
        except HubError as exc:
            session.setdefault('csrf',secrets.token_urlsafe(32))
            return render_template('login.html',error=str(exc),managed=True),exc.status

    @app.post('/logout')
    def logout():
        session.clear()
        return redirect('/login')

    @app.get('/healthz')
    def health():
        return {'ok':True}

    @app.get('/api/auth/access')
    def access():
        return {'ok':True,'authenticated':True}

    @app.get('/')
    def index():
        return render_template('index.html',csrf=session['csrf'])

    @app.get('/api/status')
    def status():
        with state.lock:
            result = runtime.status()
        feeds=rss.entries()
        for torrent in result.get('torrents',[]):
            tags={tag.strip() for tag in str(torrent.get('tags','')).split(',')}
            torrent['rss_feed']=next((e['name'] for e in feeds if 'FjordSeed-RSS-'+e['id'] in tags),
                'RSS-feed (fjernet)' if any(tag.startswith('FjordSeed-RSS-') for tag in tags) else None)
            hashes=[torrent.get(k) for k in ('hash','infohash_v1','infohash_v2')]
            torrent['benefits']=trackers.benefits.snapshot({'hashes':hashes,'name':torrent.get('name','')})
        return jsonify(result)

    @app.post('/api/torrents/preview')
    def preview_torrent():
        magnet = request.form.get('magnet','').strip()
        uploaded = request.files.get('torrent')
        if bool(magnet) == bool(uploaded):
            return jsonify(error='Vælg enten et magnetlink eller en torrentfil.'),400
        try:
            if uploaded and not uploaded.filename.lower().endswith('.torrent'):
                raise ValueError('Vælg en .torrent-fil.')
            meta = magnet_meta(magnet) if magnet else torrent_meta(uploaded.read(4*1024*1024+1))
            selected=request.form.get('tracker_id','')
            result=trackers.benefits.request(meta,selected)
            accounts={a['id']:a for a in trackers.public()['trackers']}
            matches=result.get('matches',[])
            if not matches and selected in accounts and result.get('status')!='pending':
                matches=[{'tracker_id':selected,'tracker_name':accounts[selected]['name'],'freeleech':None}]
            estimates=[ratio_estimate(m,accounts.get(m.get('tracker_id')),
                meta.get('size') if meta.get('size') is not None else m.get('size')) for m in matches]
            return jsonify({**result,'ratio_estimates':estimates})
        except ValueError as exc:
            return jsonify(error=str(exc)),400

    @app.post('/api/settings')
    def settings():
        try:
            with state.lock:
                runtime.configure(request.get_json(silent=True))
            return {'ok':True}
        except ValueError as exc:
            return jsonify(error=str(exc)),400
        except Exception:
            return jsonify(error='FjordVPN kunne ikke kontaktes. Opdatér og start FjordVPN.'),503

    @app.get('/api/trackers')
    def tracker_status():
        return jsonify(trackers.public())

    @app.get('/api/rss')
    def rss_status():
        result=rss.public()
        for feed in result['feeds']:
            feed['download_status']=rss_gate.reports.get(feed['id'],'Afventer feedposter.')
        return jsonify({**result,'download_path':str(getattr(runtime,'host_downloads','/downloads'))})

    @app.post('/api/rss')
    def save_rss():
        try:
            data=request.get_json(silent=True)
            with state.lock,rss.lock:
                ident=rss.save(data)
                sync_feed_changes()
                return {'ok':True,'id':ident}
        except ValueError as exc:
            return jsonify(error=str(exc)),400

    @app.post('/api/rss/<ident>/delete')
    def remove_rss(ident):
        try:
            with state.lock,rss.lock:
                rss.remove(ident)
                sync_feed_changes()
            return {'ok':True}
        except ValueError as exc:
            return jsonify(error=str(exc)),400

    def sync_feed_changes():
        if testing:
            return
        write_snapshot(state.root,runtime.uid,runtime.gid)
        if state.get()['enabled']:
            try:
                runtime.rpc('rss_sync',{})
            except Exception:
                # Never leave an older, less restrictive native rule running.
                runtime.stop()

    @app.post('/api/trackers')
    def save_tracker():
        try:
            ident = trackers.save(request.get_json(silent=True))
            trackers.benefits.publish_green()
            return {'ok':True,'id':ident}
        except ValueError as exc:
            return jsonify(error=str(exc)),400

    @app.post('/api/trackers/<ident>/delete')
    def delete_tracker(ident):
        try:
            trackers.remove(ident)
            trackers.benefits.publish_green()
            return {'ok':True}
        except ValueError as exc:
            return jsonify(error=str(exc)),400

    @app.post('/api/torrents')
    def add():
        try:
            policy = share_policy(request.form)
        except ValueError as exc:
            return jsonify(error=str(exc)),400
        magnet = request.form.get('magnet','').strip()
        uploaded = request.files.get('torrent')
        if bool(magnet) == bool(uploaded):
            return jsonify(error='Vælg enten et magnetlink eller en torrentfil.'),400
        if magnet:
            if len(magnet) > 16384 or not magnet.startswith('magnet:?') or '\n' in magnet or '\r' in magnet:
                return jsonify(error='Indtast et gyldigt magnetlink.'),400
            payload = {'magnet':magnet}
        else:
            if not uploaded.filename.lower().endswith('.torrent'):
                return jsonify(error='Vælg en .torrent-fil.'),400
            raw = uploaded.read(4*1024*1024)
            if not raw or raw[:1] != b'd':
                return jsonify(error='Torrentfilen er ugyldig.'),400
            payload = {'torrent':base64.b64encode(raw).decode()}
        response=app.make_response(invoke('add', {**payload, **policy}))
        if response.status_code<300:
            try:
                meta=magnet_meta(magnet) if magnet else torrent_meta(raw)
                trackers.benefits.snapshot(meta)
            except ValueError:
                # Magnet metadata can become available after the client starts.
                pass
        return response

    @app.post('/api/torrents/<ident>/<action>')
    def torrent_action(ident, action):
        if action not in ('start','stop','delete','ratio') or not re.fullmatch('[a-fA-F0-9]{40}|[a-fA-F0-9]{64}',ident):
            return jsonify(error='Ugyldig handling.'),400
        payload=request.get_json(silent=True)
        if payload is None:
            payload={}
        if not isinstance(payload,dict) or type(payload.get('confirm_early_stop',False)) is not bool:
            return jsonify(error='Ugyldig bekræftelse.'),400
        if action=='ratio':
            try:
                policy=share_policy({key:payload[key] for key in ('ratio_limit','ratio_action') if key in payload})
                if policy['ratio_limit']<1:
                    raise ValueError('Stop-ratio skal være mindst 1.')
            except ValueError as exc:
                return jsonify(error=str(exc)),400
            data={'hash':ident,'ratio_limit':policy['ratio_limit']}
            if 'ratio_action' in payload:
                data['ratio_action']=policy['ratio_action']
            return invoke(action,data)
        return invoke(action, {'hash':ident,'confirm_early_stop':payload.get('confirm_early_stop',False)})

    def invoke(action, data):
        try:
            with state.lock:
                if not state.get()['enabled']:
                    raise ValueError('Start seedboxen med en aktiv VPN først.')
                return jsonify(runtime.rpc(action, data))
        except ValueError as exc:
            return jsonify(error=str(exc)),409
        except Exception:
            return jsonify(error='qBittorrent er ikke tilgængelig. Kontrollér VPN-status.'),503

    def worker():
        checked=0
        while not stop.is_set():
            runtime.tick()
            if time.monotonic()-checked>10:
                try:
                    # Dates for RSS downloads must be discovered with no open UI.
                    with state.lock:
                        result=runtime.status()
                    for row in result.get('torrents',[]):
                        trackers.benefits.snapshot({'hashes':[row.get(k) for k in ('hash','infohash_v1','infohash_v2')],
                            'name':row.get('name','')})
                except Exception:
                    pass
                checked=time.monotonic()
            stop.wait(3)

    if not testing:
        threading.Thread(target=worker, daemon=True).start()
        threading.Thread(target=trackers.run, args=(stop,), daemon=True).start()
        threading.Thread(target=trackers.benefits.run, args=(stop,), daemon=True).start()
        threading.Thread(target=rss_gate.run, args=(stop,), daemon=True).start()
    return app


if __name__ == '__main__':
    from waitress import serve
    application = create_app()
    def shutdown(*_):
        application.extensions['stop'].set()
        with application.extensions['state'].lock:
            application.extensions['runtime'].stop()
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    serve(application, host='0.0.0.0', port=8088, threads=8)
