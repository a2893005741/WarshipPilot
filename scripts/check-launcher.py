"""Run the packaged EXE in a Chinese path, open it twice, and exit cleanly."""
import json
import argparse
from pathlib import Path
import subprocess
import time
import urllib.request

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--dist', default='dist')
parser.add_argument('--port', type=int, default=22683)
options = parser.parse_args()
data = root / 'evidence' / ('launcher-' + options.dist)
base = f'http://127.0.0.1:{options.port}'
args = [str(root / options.dist / "WarshipPilot" / "WarshipPilot.exe"), "--no-browser", "--port", str(options.port), "--data-dir", str(data)]
first = subprocess.Popen(args)
try:
    for _ in range(60):
        try:
            with urllib.request.urlopen(base + "/health", timeout=1) as response:
                health = json.load(response)
                assert health["product"] == "WarshipPilot"
            break
        except OSError:
            time.sleep(0.2)
    else:
        raise AssertionError("Packaged service did not start")
    second = subprocess.Popen(args)
    assert second.wait(timeout=10) == 0
    assert first.poll() is None
    key = json.loads((data / "access.json").read_text(encoding="utf-8"))["key"]
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    with urllib.request.urlopen(urllib.request.Request(base + '/api/legacy-catalog', headers=headers), timeout=10) as response:
        catalog = json.load(response)
        assert catalog['stats']['point_expressions'] == 624
    request = urllib.request.Request(base + "/api/shutdown", data=b"{}", headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        assert json.load(response)["ok"]
    assert first.wait(timeout=15) == 0
    result = {"version": health['version'], "legacy_rules": 624, "chinese_path_exe": True, "second_launcher_exits": True, "first_server_stays_alive": True, "graceful_exit": True}
    (root / "evidence" / (options.dist + "-launcher-check.json")).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
finally:
    if first.poll() is None:
        first.terminate()
