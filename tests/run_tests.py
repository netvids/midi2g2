#!/usr/bin/env python3
"""Runs every case in cases.txt through the Python tool and checks the files with verify.py. If the web app (web/ and
tests/compare.js) is present, it also converts the same cases with the web app's code (node) and checks that both
produce identical files.
Needs: g2ools (python/setup_g2ools.sh), pip install -r requirements.txt, and node for the web comparison."""
import os, subprocess, sys, tempfile, shlex
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); PY = os.path.join(ROOT, 'python')
out = tempfile.mkdtemp(prefix='midi2g2-tests-'); failed = 0
for line in open(os.path.join(HERE, 'cases.txt')):
    if not line.strip(): continue
    cid, f, args = line.rstrip('\n').split('|')
    src = os.path.join(HERE, 'inputs', f if '.' in f else f + '.mid')
    r = subprocess.run([sys.executable, os.path.join(PY, 'midi2g2.py'), src, '--out', os.path.join(out, cid)] + shlex.split(args), capture_output=True, text=True)
    if r.returncode: print(cid, 'Python tool failed:', r.stderr.strip()[-300:]); failed += 1; continue
    v = subprocess.run([sys.executable, os.path.join(PY, 'verify.py'), os.path.join(out, cid)], capture_output=True, text=True)
    if v.returncode or '\n!' in v.stdout: print(cid, 'verify.py found a problem:\n' + v.stdout[-400:]); failed += 1
print(f'Python: {sum(1 for l in open(os.path.join(HERE, "cases.txt")) if l.strip())} cases converted into {out}')
cmp = os.path.join(HERE, 'compare.js')
if os.path.isfile(cmp) and os.path.isdir(os.path.join(ROOT, 'web')):
    rc = subprocess.run(['node', cmp, out]).returncode
else:
    print('web app not present: skipping the comparison with the web version'); rc = 0
sys.exit(1 if failed or rc else 0)
