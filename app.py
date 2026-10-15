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

from flask import Flask, jsonify, redirect, render_template, request, session, send_file
from werkzeug.security import check_password_hash, generate_password_hash

from hub import Hub, HubError
from runtime import Runtime
from event_notifier import EventNotifier
from qbit_rpc import share_policy, extra_seed_hours
from trackers import Trackers
from torrent_meta import torrent_meta, magnet_meta
from rss import Rss,write_snapshot,validate_feed
from rss_gate import RssGate
from benefits import ratio_estimate
from state import State, atomic
from covers import Covers
from storage import Storage


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
    notifier = EventNotifier(state.root, hub, 'fjordseed')
    trackers = Trackers(state.root)
    covers = Covers(state.root)
    trackers.benefits.publish_green()
    rss = Rss(state.root)
    rss_gate = RssGate(rss,runtime,state,trackers.benefits)
    app.extensions.update(state=state, runtime=runtime, stop=stop, hub=hub, trackers=trackers, rss=rss, covers=covers, event_notifier=notifier)
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
        if request.endpoint == 'bot_seeding':
            supplied = request.headers.get('X-Hub-Key', '')
            if not hub.enabled or not hub.key or not secrets.compare_digest(hub.key, supplied):
                return jsonify(ok=False, error='Ugyldig appnøgle.'), 403
            return
        if request.endpoint in ('login','hub_login','static','health','logout'):
            return
        if session.get('authenticated') and hub.enabled:
            try:
                member = hub.current(session.get('hub_uid'), force=request.path == '/api/auth/access' and request.args.get('fresh') == '1')
            except HubError as exc:
                if exc.status != 503:
                    session.clear()
                    session['hub_access_revoked'] = True
                return jsonify(error=str(exc), error_code='access_revoked' if exc.status != 503 else 'hub_unavailable'), exc.status
            if member.get('email_required') and request.endpoint != 'hub_email_update':
                from hub_email import required_response
                return required_response()
        if not session.get('authenticated'):
            if request.path.startswith('/api/'):
                return jsonify(error='Log ind for at fortsætte.', authenticated=False),401
            return redirect('/login')

    @app.after_request
    def headers(response):
        response.headers.update({'Cache-Control':'no-store','X-Content-Type-Options':'nosniff',
            'X-Frame-Options':'DENY','Referrer-Policy':'same-origin',
            'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"})
        if request.endpoint=='cover' and response.status_code==200:
            response.headers['Cache-Control']='private, max-age=3600'
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
                        user = hub.authenticate(request.form.get('username',''), request.form.get('password',''), request.form.get('first_login_email',''), request.form.get('first_login_password',''), request.form.get('first_login_password_confirm',''))
                        if user.get('email_required') or user.get('must_change_password'):
                            return render_template('login.html', managed=True, email_required=user.get("email_required"), password_required=user.get("must_change_password"), error=user.get('email_error') or 'Første login: Udfyld oplysningerne og vælg din egen adgangskode.')
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

    @app.post('/api/auth/email')
    def hub_email_update():
        from hub_email import submit_email
        if not hub.enabled:
            return jsonify(ok=False, error='Kræver FjordHub-login.'), 403
        try:
            member = hub.current(session.get('hub_uid'), force=True)
            response = submit_email(member, hub.call)
            hub.expires = 0
            return response
        except HubError as exc:
            return jsonify(ok=False, error=str(exc)), exc.status

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
            torrent['cover']=next((url for m in torrent['benefits'].get('matches',[])
                                  if (url:=covers.request(m.get('poster')))),None)
        return jsonify(result)

    @app.get('/api/hub/bot/seeding')
    def bot_seeding():
        # A separate read-only projection: no session, paths, tracker URLs or keys.
        with state.lock:
            result = runtime.status()
        if not result.get('torrents_available'):
            return jsonify(ok=False, error='FjordSeed kan ikke hente torrentstatus lige nu.'), 503
        fields = ('name', 'state', 'progress', 'upspeed', 'credited_ratio', 'ratio',
                  'ratio_limit', 'ratio_only', 'seeding_time', 'seeding_time_limit',
                  'seeding_unlimited', 'seeding_goal_reached', 'waiting_for_downloaders')
        rows = result.get('torrents', [])
        return jsonify(ok=True, total=len(rows), more=len(rows) > 500,
                       torrents=[{k: row[k] for k in fields if k in row} for row in rows[:500]])

    @app.get('/api/covers/<ident>')
    def cover(ident):
        path=covers.path(ident)
        if path is None:
            return '',404
        try:
            with path.open('rb') as image:
                signature=image.read(12)
            mimetype='image/jpeg' if signature.startswith(b'\xff\xd8\xff') else 'image/png' if signature.startswith(b'\x89PNG') else 'image/webp'
            return send_file(path,mimetype=mimetype,conditional=True)
        except FileNotFoundError:
            return '',404

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

    @app.route('/api/storage', methods=['GET','POST'])
    def storage_settings():
        try:
            if hub.enabled and hub.current(session.get('hub_uid'), force=True).get('hub_role') != 'admin':
                return jsonify(error='Valg af servermapper kræver en FjordHub-administrator.'),403
            storage = Storage(runtime)
            if request.method == 'POST':
                data = request.get_json(silent=True)
                if not isinstance(data,dict):
                    raise ValueError('Vælg en mappe.')
                return jsonify(ok=True, **storage.select(data.get('path')))
            if request.args.get('browse') == '1':
                return jsonify(storage.helper('browse',request.args.get('path','')))
            if request.args.get('proxmox') == '1':
                if not hub.enabled:
                    raise ValueError('Proxmox-oversigten kræver en forbindelse til FjordHub.')
                try:
                    inventory = hub.call('/api/hub/apps/fjordseed/library',
                        {'user_id':session.get('hub_uid')},method='GET',timeout=55)
                except HubError as exc:
                    # The user's session was checked above. This rejection belongs
                    # to the app-to-app storage request, not the browser login.
                    # Older Hub versions reject the unknown route with HTTP 401.
                    if exc.status == 401:
                        return jsonify(error='FjordHub afviste lageroversigten. Opdatér FjordHub til nyeste version. '
                            'Hvis fejlen fortsætter, skal FjordSeeds forbindelse til FjordHub kontrolleres.',
                            error_code='storage_integration_unavailable'),503
                    raise
                return jsonify(inventory)
            return jsonify(storage.public())
        except HubError as exc:
            return jsonify(error=str(exc)),exc.status
        except ValueError as exc:
            return jsonify(error=str(exc)),400
        except Exception:
            app.logger.exception('Storage operation failed')
            return jsonify(error='Lageret kunne ikke åbnes. Kontrollér Docker og skriverettigheder.'),503

    @app.get('/api/trackers')
    def tracker_status():
        return jsonify(trackers.public())

    @app.get('/api/rss')
    def rss_status():
        result=rss.public()
        for feed in result['feeds']:
            feed['download_status']=rss_gate.reports.get(feed['id'],'Afventer feedposter.')
        return jsonify({**result,'download_path':Storage(runtime).public()['path'] if hasattr(runtime,'host_downloads') else '/downloads'})

    @app.get('/api/rss/<ident>/history')
    def rss_download_history(ident):
        try:
            return jsonify(downloads=rss.download_history(ident))
        except (OSError, json.JSONDecodeError):
            return jsonify(error='Historikken kunne ikke læses. Prøv igen.'),503
        except ValueError as exc:
            return jsonify(error=str(exc)),404

    @app.post('/api/rss')
    def save_rss():
        return save_rss_data(request.get_json(silent=True))

    @app.post('/api/rss/<ident>/enabled')
    def set_rss_enabled(ident):
        data=request.get_json(silent=True)
        if not isinstance(data,dict) or type(data.get('enabled')) is not bool:
            return jsonify(error='Vælg tændt eller slukket for feedet.'),400
        return save_rss_data({'id':ident,'enabled':data['enabled']})

    def save_rss_data(data):
        try:
            with state.lock,rss.lock:
                current=next((e for e in rss.entries() if isinstance(data,dict) and e['id']==data.get('id')),None)
                if isinstance(data,dict) and data.get('id') and not current:
                    raise ValueError('Feedet findes ikke længere.')
                merged={**(current or {}),**data} if isinstance(data,dict) else data
                if isinstance(merged,dict) and not merged.get('url'):
                    merged['url']=(current or {}).get('url','')
                validated=validate_feed(merged)
                retained_pause=(current and not validated['enabled']
                    and validated['required_badges']==current.get('required_badges',[])
                    and validated['tracker_id']==current.get('tracker_id',''))
                if validated['required_badges'] and not retained_pause:
                    from urllib.parse import urlsplit
                    with trackers.lock:
                        tracker=next((e for e in trackers.entries() if e['id']==validated['tracker_id']),None)
                        if not tracker or tracker['provider']!='nordicbytes':
                            raise ValueError('Vælg en NordicBytes-tracker til badgekontrol.')
                        if urlsplit(validated['url']).hostname not in ('nordicbytes.org','www.nordicbytes.org'):
                            raise ValueError('Badgekontrol understøttes aktuelt for NordicBytes-feeds.')
                        if validated['enabled'] and not trackers.badge_ready(tracker['id']):
                            raise ValueError('Trackerens API-adgang skal være aktiv, før feedet kan startes med badgekrav.')
                ident=rss.save(merged)
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
                extra=extra_seed_hours(payload['extra_seed_hours']) if 'extra_seed_hours' in payload else None
            except ValueError as exc:
                return jsonify(error=str(exc)),400
            data={'hash':ident,'ratio_limit':policy['ratio_limit']}
            if extra is not None:
                data['extra_seed_hours']=extra
            if 'ratio_action' in payload:
                data['ratio_action']=policy['ratio_action']
            return invoke(action,data)
        data={'hash':ident,'confirm_early_stop':payload.get('confirm_early_stop',False)}
        if action=='delete':
            if type(payload.get('delete_files',False)) is not bool:
                return jsonify(error='Vælg om downloadede filer skal slettes.'),400
            data['delete_files']=payload.get('delete_files',False)
        return invoke(action, data)

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
                    if result.get('torrents_available'):
                        notifier.observe_seed(result.get('torrents', []), rss.entries())
                    for row in result.get('torrents',[]):
                        trackers.benefits.snapshot({'hashes':[row.get(k) for k in ('hash','infohash_v1','infohash_v2')],
                            'name':row.get('name','')})
                except Exception:
                    pass
                checked=time.monotonic()
            stop.wait(3)

    if not testing:
        threading.Thread(target=worker, daemon=True).start()
        threading.Thread(target=notifier.run, args=(stop,), daemon=True).start()
        threading.Thread(target=trackers.run, args=(stop,), daemon=True).start()
        threading.Thread(target=trackers.benefits.run, args=(stop,), daemon=True).start()
        threading.Thread(target=covers.run, args=(stop,), daemon=True).start()
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
