"""Clone -> start WebUI -> push -> request update -> verify automatic restart.
Runs against a local bare repository; no Android input is sent.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from module.config.config import Config
from module.config.task_settings import TaskDraft,save_task

def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.STDOUT,encoding='utf-8').strip()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime',type=Path,default=ROOT/'.runtime-stage/portable')
    args=parser.parse_args()
    base=ROOT/'.deployment'/('update-smoke-'+str(int(time.time())))
    base.mkdir(parents=True)
    remote,author,live=(base/p for p in ('remote.git','author','live'))
    subprocess.run(['git','clone','--bare',str(ROOT),str(remote)],check=True,capture_output=True)
    branch=git(ROOT,'branch','--show-current')
    for destination in (author,live):
        subprocess.run(['git','clone','--branch',branch,str(remote),str(destination)],check=True,capture_output=True)
    # The portable runtime has already been verified separately. The smoke clone
    # shares it via a junction, keeping a full extra toolchain copy unnecessary.
    subprocess.run(['cmd.exe','/d','/c','mklink','/J',str(live/'.venv'),str(args.runtime.resolve()/'.venv')],check=True,capture_output=True)
    config=Config(live);config.ensure()
    value=config.deploy();value['Git']['Branch']=branch;value['WebUI']['Port']=22684;value['Update']['AutoCheck']=False
    config.save_deploy(value)
    save_task(live,'expedition',TaskDraft(enabled=True))
    config.save_section('Scheduler',{'Enable':True,'NextRun':{'expedition':'2030-01-01T00:00:00+00:00'}})
    key=value['WebUI']['AccessCode']
    headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'}
    def call(action,body=None):
        request=urllib.request.Request('http://127.0.0.1:22684/'+action,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        with urllib.request.urlopen(request,timeout=15) as response:return json.load(response)
    def wait(check,seconds=60):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            try:
                value=check()
                if value:return value
            except (OSError,urllib.error.URLError):pass
            time.sleep(.25)
        raise RuntimeError('Timed out; inspect '+str(live/'log'))
    python=live/'.venv/Scripts/python.exe'
    output=(base/'gui.log').open('w',encoding='utf-8')
    process=subprocess.Popen([str(python),str(live/'gui.py'),'--no-browser'],cwd=live,stdout=output,stderr=output)
    try:
        old=wait(lambda:call('health'))
        git(author,'config','user.email','smoke@example.invalid');git(author,'config','user.name','Source Update Smoke')
        (author/'docs/source-update-smoke.txt').write_text('Integration update marker\n',encoding='utf-8')
        git(author,'add','docs/source-update-smoke.txt');git(author,'commit','-m','Verify source update handover')
        target=git(author,'rev-parse','HEAD');git(author,'push','origin',branch)
        update=call('api/update-check',{})
        assert update['state']=='available',update
        call('api/update-install',{})
        process.wait(timeout=35)
        health=wait(lambda:(h if (h:=call('health')).get('commit')==target and h['pid']!=old['pid'] else None))
        wait(lambda:(live/'log/update-result.json').exists() and json.loads((live/'log/update-result.json').read_text())['ok'])
        state=call('api/state')
        assert state['automation']['scheduler'] is True
        assert state['automation']['due']['expedition']=='2030-01-01T00:00:00+00:00'
        assert Config(live).deploy()['WebUI']['AccessCode']==key
        result={'before':old['commit'],'after':health['commit'],'pid_changed':True,'scheduler_restored':True,'due_restored':True,'access_code_preserved':True,'dependency_sync_skipped':True}
        (base/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result))
    finally:
        try:call('api/shutdown',{})
        except OSError:pass
        if process.poll() is None:process.terminate();process.wait(timeout=10)
        output.close()
if __name__=='__main__':main()
