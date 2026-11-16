"""Exercise the running remote release. Does not send any Android input."""
import io
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parent.parent
HOST = "http://DESKTOP-3F63TNA:22680"
KEY = json.loads((ROOT / "evidence" / "remote-access.json").read_text(encoding="utf-8-sig"))["key"]
results = {}


def request(action, payload=None, raw=False):
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(HOST + "/api/" + action, data=body,
                                 headers={"Authorization": "Bearer " + KEY, "Content-Type": "application/octet-stream" if isinstance(payload, bytes) else "application/json"})
    with urllib.request.urlopen(req, timeout=35) as response:
        return response.read() if raw else json.load(response)


state = request("state")
assert state["serial"] == "127.0.0.1:16416" and state["frame"]["width"] == 1280
assert state["frame"]["height"] == 720 and state["read_only"]
results["real_device"] = {"serial": state["serial"], "game_version": state["profile"]["version"], "size": [1280,720]}

try:
    urllib.request.urlopen(HOST + "/api/state", timeout=10)
    raise AssertionError("Unauthenticated API was accepted")
except urllib.error.HTTPError as exc:
    assert exc.code == 401
results["api_requires_access_code"] = True

try:
    request("select", {"serial": "emulator-5554"})
    raise AssertionError("Non-game device was accepted")
except urllib.error.HTTPError as exc:
    assert exc.code == 400
assert request("state")["serial"] == "127.0.0.1:16416"
results["other_game_rejected"] = True

request("control", {"action": "pause"})
before = request("state")["frame"]["id"]
time.sleep(4)
assert request("state")["frame"]["id"] == before
results["pause_stops_capture"] = True

samples = request("samples")
assert samples and samples[0]["label"] == "母港" and samples[0]["roi"]
image = request("sample-image?id=" + samples[0]["id"], raw=True)
replay = request("replay", image)
assert replay["label"] == "母港" and replay["score"] == 1
results["saved_sample_replay"] = replay

request("control", {"action": "resume"})
request("session-start", {})
deadline = time.monotonic() + 25
while time.monotonic() < deadline:
    state = request("state")
    if state["frame"]["id"] > before and state["session_count"] >= 2:
        break
    time.sleep(2)
assert state["frame"]["id"] > before and state["session_count"] >= 2
request("session-stop", {})
results["resume_and_continuous_archive"] = {"saved_frames": state["session_count"], "live_frame_id": state["frame"]["id"]}

report = request("legacy-report", {"config": {}})
assert report["total_known"] == 518 and len(report["fields"]) == 518 and not report["activated"]
assert sum(report["counts"].values()) == 518
results["legacy_inventory_coverage"] = report["total_known"]

diagnostic = request("diagnostic", raw=True)
(ROOT / "evidence" / "remote-diagnostic.zip").write_bytes(diagnostic)
with zipfile.ZipFile(io.BytesIO(diagnostic)) as archive:
    names = archive.namelist()
    assert "last-frame.png" in names and any("feature.png" in name for name in names)
    assert any(name.startswith("sessions/") and name.endswith(".png") for name in names)
    assert not any("access.json" in name or "console-url" in name for name in names)
    assert KEY.encode() not in archive.read("state.json")
results["diagnostic_archive"] = {"files": len(names), "bytes": len(diagnostic), "access_code_excluded": True}
(ROOT / "evidence" / "remote-latest.png").write_bytes(request("frame", raw=True))
(ROOT / "evidence" / "practical-check.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(results, ensure_ascii=False, indent=2))
