"""Small real-image/API smoke check; no Android input."""
import argparse
import base64
import io
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import zipfile

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--remote', action='store_true')
options = parser.parse_args()
host = 'http://DESKTOP-3F63TNA:22680' if options.remote else 'http://127.0.0.1:22681'
access = root / 'evidence' / ('remote-access.json' if options.remote else 'integration-data/access.json')
key = json.loads(access.read_text(encoding='utf-8-sig'))['key']


def call(action, payload=None, raw=False):
    request = urllib.request.Request(host + '/api/' + action,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=35) as response:
        return response.read() if raw else json.load(response)


stats = call('legacy-catalog')['stats']
assert stats['point_expressions'] == 624 and stats['points'] == 3414
profile = call('state')['legacy']['profile']
image = base64.b64encode((root / 'evidence/remote-first-frame.png').read_bytes()).decode()
body = {'profile': profile, 'image_base64': image, 'rule_id': 'legacy-2120'}
match = call('legacy-check', body)
assert match['matched'] and match['matched_points'] == 10
rgb = call('legacy-check', {**body, 'profile': {**profile, 'color_order': 'RGB'}})
assert not rgb['matched']
assert call('legacy-check', {**body, 'rule_id': 'legacy-1231'})['status'] == 'unavailable'
try:
    call('legacy-check', {**body, 'profile': {**profile, 'base_width': 600}})
    raise AssertionError('Aspect mismatch accepted')
except urllib.error.HTTPError as exc:
    assert exc.code == 400
try:
    urllib.request.urlopen(host + '/api/legacy-download', timeout=10)
    raise AssertionError('Unauthenticated archive accepted')
except urllib.error.HTTPError as exc:
    assert exc.code == 401
with zipfile.ZipFile(io.BytesIO(call('legacy-download', raw=True))) as archive:
    assert len(archive.namelist()) == 12
result = {'catalog': stats, 'mother_port': {k: match[k] for k in ('id','matched_points','total_points','mean_delta')},
          'rgb_negative_control': not rgb['matched'], 'malformed_rule_preserved': True,
          'aspect_mismatch_rejected': True, 'authenticated_asset_export': True}
if options.remote:
    state = call('state')
    if state['serial'] != '127.0.0.1:16416':
        call('select', {'serial': '127.0.0.1:16416'})
    call('legacy-settings', {'profile': profile, 'observing': True})
    before = (call('state')['frame'] or {}).get('id', 0)
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        state = call('state')
        observation = state['legacy']['result']
        if observation and observation.get('frame_id', 0) > before and not observation.get('error'):
            break
        time.sleep(1)
    else:
        raise AssertionError('No fresh color observation')
    assert state['frame']['width'] == 1280 and state['frame']['height'] == 720
    result['remote'] = {'version': state['version'], 'serial': state['serial'], 'size': [1280,720],
        'samples_count': state['samples_count'], 'frame_before': before, 'frame_after': observation['frame_id'],
        'fully_matched': observation['fully_matched'], 'latency_ms': observation['latency_ms'],
        'top': [{k:c[k] for k in ('id','matched_points','total_points','matched')} for c in observation['candidates'][:3]]}
    (root / 'evidence/integration-live.png').write_bytes(call('frame', raw=True))
name = 'v0.2-remote-integration.json' if options.remote else 'v0.2-local-integration.json'
(root / 'evidence' / name).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
