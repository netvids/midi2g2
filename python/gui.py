#!/usr/bin/env python3
"""midi2g2 in your browser, with this Python tool doing the conversion.

    python python/gui.py              # opens http://127.0.0.1:8000 in your browser
    python python/gui.py --port 8080 --no-browser

Serves the page in gui/ on this computer only (127.0.0.1). The page sends the file you choose to this program, which
reads and converts it with midi2g2.py, exactly like the command line. Nothing leaves your computer. Ctrl+C stops it."""
import sys, os, io, json, argparse, tempfile, shutil, threading, uuid, zipfile, webbrowser
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
PAGE = os.path.join(os.path.dirname(HERE), 'gui')
import midi2g2 as M
from gm import GM_NAMES

_T = json.load(open(os.path.join(HERE, 'templates.json'), encoding='utf-8'))
META = dict(sounds=_T['sounds'], chord_sounds=_T['chord_sounds'], chain_capacity=_T['chain_capacity'], gm=GM_NAMES)
LOCK = threading.Lock()                       # g2ools builds patches in module-level state: one conversion at a time
SONGS = {}                                    # token -> dict(S, path, warnings); the last few files read
TMP = tempfile.mkdtemp(prefix='midi2g2-gui-')

def midi_meta(path):
    """(quarter notes per bar, warnings) of a MIDI file, as the page shows them."""
    import mido
    f = mido.MidiFile(path); tempos, sig = set(), None
    for tr in f.tracks:
        for msg in tr:
            if msg.type == 'set_tempo': tempos.add(msg.tempo)
            elif msg.type == 'time_signature' and sig is None: sig = msg.numerator * 4 / msg.denominator
    return sig or 4, (['The file changes tempo: only the first tempo is used.'] if len(tempos) > 1 else [])

def analyse(data, name, bends, song):
    d = tempfile.mkdtemp(dir=TMP); path = os.path.join(d, os.path.basename(name) or 'song.mid')
    open(path, 'wb').write(data)
    S = M.load_song(path, bends, song)
    if S['info']: bpb, warnings = 4, []
    else: bpb, warnings = midi_meta(path)
    token = uuid.uuid4().hex
    SONGS[token] = dict(S=S, warnings=warnings)
    while len(SONGS) > 32: SONGS.pop(next(iter(SONGS)))      # the page sends its file again if it was dropped (410)
    lines = []
    for l in S['lines']:
        x = dict(l, snd=[[M.default_sound(l, i, n) for i in range(n)] for n in range(1, 5)])
        lines.append(x)
    info = S['info']
    nsf = None if not info else dict(songs=info['songs'], song=info['song'], title=info.get('title', ''), artist=info.get('artist', ''),
                                     labels=info.get('labels', []), times=info.get('times', []), loopEnd=info.get('loop_end'),
                                     chips=info.get('chips', 0), chip='sid' if S['kind'] == 'SID' else 'nsf')
    end = max((n[1] for l in S['lines'] for n in l['notes']), default=0)
    return dict(token=token, lines=lines, bpm=S['bpm'], warnings=warnings, name=S['name'], fileName=os.path.basename(name),
                beatsPerBar=bpb, endBeat=end, nsf=nsf,
                picks={n: [l['id'] for l in M.default_pick(S['lines'], n)] for n in range(1, 5)} if S['lines'] else {})

class Gone(Exception): pass

def make_plan(req):
    song = SONGS.get(req.get('token'))
    if not song: raise Gone('This file is no longer loaded here. Choose it again.')
    o = req.get('opts') or {}
    sec = o.get('range')
    P = M.plan(song['S'], pick=o.get('pick') or None, parts=o.get('parts') or 3, grid=o.get('grid') or None,
               sounds=o.get('sound'), chain=bool(o.get('chain')), section=tuple(sec) if sec else None, bpm=o.get('bpm') or None)
    return song, P

def convert(req):
    song, P = make_plan(req)
    return dict(secs=P['secs'], spb=P['spb'], g2bpm=P['g2bpm'], nbars=P['nbars'], nperf=P['nperf'], perPerf=P['per_perf'],
                used=P.get('used'), chain=P['chain'], report=P['report'], summary=P['summary'],
                warnings=song['warnings'] + ([P['note']] if P['note'] else []), preview=P['preview'])

def save(req):
    song, P = make_plan(req)
    folder = f"{P['name']} G2"; out = tempfile.mkdtemp(dir=TMP)
    try:
        M.write(P, os.path.join(out, folder))
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
            for fn in sorted(os.listdir(os.path.join(out, folder))): z.write(os.path.join(out, folder, fn), f'{folder}/{fn}')
        return folder + '.zip', buf.getvalue()
    finally: shutil.rmtree(out, ignore_errors=True)

def page():
    html = open(os.path.join(PAGE, 'index.html'), encoding='utf-8').read()
    return html.replace('<!--M2G-META-->', '<script type="application/json" id="tpl">' + json.dumps(META).replace('</', '<\\/') + '</script>')

STATIC = {'/player.js': 'player.js', '/api.js': 'api.js', '/app.js': 'app.js'}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, code, body, ctype, extra=()):
        if isinstance(body, str): body = body.encode('utf-8')
        self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        for k, v in extra: self.send_header(k, v)
        self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        p = urlparse(self.path).path
        if p in ('/', '/index.html'): return self.send(200, page(), 'text/html; charset=utf-8')
        if p in STATIC: return self.send(200, open(os.path.join(PAGE, STATIC[p]), 'rb').read(), 'text/javascript; charset=utf-8')
        self.send(404, 'not found', 'text/plain')
    def do_POST(self):
        u = urlparse(self.path); body = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        try:
            with LOCK:
                if u.path == '/api/analyse':
                    q = {k: v[0] for k, v in parse_qs(u.query).items()}
                    r = analyse(body, q.get('name', 'song.mid'), q.get('bends', 'main'), int(q['song']) if q.get('song') else None)
                    return self.send(200, json.dumps(r), 'application/json')
                req = json.loads(body or b'{}')
                if u.path == '/api/convert': return self.send(200, json.dumps(convert(req)), 'application/json')
                if u.path == '/api/save':
                    name, data = save(req)
                    return self.send(200, data, 'application/zip', [('Content-Disposition', f'attachment; filename="{name}"')])
            self.send(404, 'not found', 'text/plain')
        except Gone as e:
            self.send(410, json.dumps(dict(error=str(e))), 'application/json')
        except (ValueError, KeyError, IndexError, EOFError) as e:
            self.send(400, json.dumps(dict(error=str(e) or e.__class__.__name__)), 'application/json')
        except Exception as e:                                   # keep the server running; show the problem on the page
            import traceback; traceback.print_exc()
            self.send(500, json.dumps(dict(error=f'{e.__class__.__name__}: {e}')), 'application/json')

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--port', type=int, default=8000); ap.add_argument('--no-browser', action='store_true')
    a = ap.parse_args()
    srv = None
    for port in range(a.port, a.port + 20):                     # the next free port if this one is taken
        try: srv = ThreadingHTTPServer(('127.0.0.1', port), Handler); break
        except OSError: continue
    if not srv: raise SystemExit(f'No free port from {a.port} to {a.port + 19}: try --port with another number.')
    url = f'http://127.0.0.1:{srv.server_address[1]}/'
    print(f'midi2g2 is running at {url}\nOpen it in your browser if it did not open by itself. Press Ctrl+C to stop.')
    if not a.no_browser: threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try: srv.serve_forever()
    except KeyboardInterrupt: print('\nStopped.')
    finally: srv.server_close(); shutil.rmtree(TMP, ignore_errors=True)

if __name__ == '__main__':
    main()
