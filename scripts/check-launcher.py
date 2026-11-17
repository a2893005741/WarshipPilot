"""Smoke-test the source WebUI without a game or any device input."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module.config.config import Config

def main():
    with tempfile.TemporaryDirectory() as temporary:
        state_root=Path(temporary)
        process=subprocess.Popen([sys.executable,str(ROOT/'gui.py'),'--root',str(state_root),'--port','22683','--no-browser'],cwd=ROOT)
        try:
            deadline=time.monotonic()+25
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('GUI failed to start')
                try:
                    with urllib.request.urlopen('http://127.0.0.1:22683/health',timeout=1) as response:health=json.load(response)
                    break
                except OSError:time.sleep(.2)
            else:raise RuntimeError('No health response')
            key=Config(state_root).deploy()['WebUI']['AccessCode']
            headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'}
            with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:22683/api/state',headers=headers)) as response:
                state=json.load(response)
            assert state['automation']['scheduler'] is False
            assert health['product']=='WarshipPilot'
            for action in ('launcher-prepare', 'launcher-cancel'):
                with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:22683/api/'+action,data=b'{}',headers=headers)) as response:
                    result=json.load(response)
                assert result.get('ready',result.get('ok')) is True

            with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:22683/api/shutdown',data=b'{}',headers=headers)) as response:response.read()
            process.wait(timeout=30)
            print(json.dumps({'health':health,'scheduler_default':False,'authenticated_state':True,'clean_shutdown':process.returncode==0},ensure_ascii=False))
        finally:
            if process.poll() is None:process.terminate();process.wait(timeout=10)
if __name__=='__main__':main()
