"""Git updates tested against a real local bare remote, without GitHub."""
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from deploy.git import Git
from module.config.config import Config
from module.api.update_service import Updater


def git(root,*args):
    return subprocess.check_output(['git','-C',str(root),*args],stderr=subprocess.STDOUT,text=True,encoding='utf-8').strip()


class UpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.remote=self.base/'remote.git'
        subprocess.run(['git','init','--bare',str(self.remote)],check=True,capture_output=True)
        self.author=self.base/'author'
        subprocess.run(['git','clone',str(self.remote),str(self.author)],check=True,capture_output=True)
        git(self.author,'config','user.email','test@example.invalid')
        git(self.author,'config','user.name','Test')
        git(self.author,'switch','-c','main')
        (self.author/'.gitignore').write_text('config/deploy.yaml\nconfig/warship.json\nlog/\n',encoding='utf-8')
        self.push('initial')
        self.live=self.base/'live'
        subprocess.run(['git','clone','-b','main',str(self.remote),str(self.live)],check=True,capture_output=True)
        Config(self.live).ensure()
        self.stop=threading.Event()
        self.addCleanup(self.stop.set)
        self.busy=True
        self.quiesced=[]
        self.u=Updater(self.live,{},lambda:self.busy,lambda:None,lambda *a:None,
                       self.quiesced.append,self.stop)

    def push(self,message):
        (self.author/'code.txt').write_text(message,encoding='utf-8')
        git(self.author,'add','.')
        git(self.author,'commit','-m',message)
        git(self.author,'push','origin','main')

    def test_lists_and_applies_commit_without_touching_config(self):
        before=Config(self.live).deploy_file.read_bytes()
        self.push('new behavior')
        state=self.u.check()
        self.assertEqual(state['state'],'available')
        self.assertEqual(state['latest']['commits'][0]['subject'],'new behavior')
        Git(self.live).apply(state['latest']['version'])
        self.assertEqual((self.live/'code.txt').read_text(),'new behavior')
        self.assertEqual(Config(self.live).deploy_file.read_bytes(),before)
        self.assertEqual(self.u.check()['state'],'current')

    def test_dirty_files_block_reset(self):
        self.push('new')
        (self.live/'code.txt').write_text('local edit')
        with self.assertRaisesRegex(ValueError,'未提交'):
            Git(self.live).apply()
        self.assertEqual((self.live/'code.txt').read_text(),'local edit')

    def test_untracked_program_file_blocks_reset(self):
        (self.live/'user-script.py').write_text('mine')
        with self.assertRaises(ValueError):
            Git(self.live).apply()

    def test_divergence_is_not_overwritten(self):
        git(self.live,'config','user.email','test@example.invalid')
        git(self.live,'config','user.name','Test')
        (self.live/'code.txt').write_text('local commit')
        git(self.live,'commit','-am','local commit')
        self.push('remote commit')
        self.assertEqual(self.u.check()['state'],'error')
        self.assertIn('分叉',self.u.state()['error'])

    def test_waits_for_task_and_hands_over_once(self):
        self.push('new')
        self.u.check()
        done=threading.Event()
        with patch.object(self.u,'_handover',side_effect=done.set) as handover:
            self.u.install()
            self.assertEqual(self.quiesced,[True])
            self.assertFalse(done.wait(.35))
            self.busy=False
            self.assertTrue(done.wait(3))
            handover.assert_called_once()

    def test_changed_target_requires_recheck(self):
        self.push('one')
        target=self.u.check()['latest']['version']
        self.push('two')
        with self.assertRaisesRegex(ValueError,'改变'):
            Git(self.live).apply(target)
        self.assertEqual((self.live/'code.txt').read_text(),'initial')

    def test_mirror_fetch(self):
        deployment=Config(self.live).deploy()
        deployment['Git']['Repository']=str(self.remote)
        Config(self.live).save_deploy(deployment)
        git(self.live,'remote','set-url','origin',str(self.base/'unreachable.git'))
        self.push('mirror works')
        self.assertEqual(self.u.check()['state'],'available')

    def test_failed_dependencies_restore_previous_commit(self):
        from deploy.installer import install
        previous = git(self.live, 'rev-parse', 'HEAD')
        self.push('requires new dependencies')
        with patch('deploy.installer.pip.sync', side_effect=[RuntimeError('dependency failed'), True]):
            with self.assertRaisesRegex(RuntimeError, 'dependency failed'):
                install(self.live)
        self.assertEqual(git(self.live, 'rev-parse', 'HEAD'), previous)
        self.assertEqual((self.live/'code.txt').read_text(), 'initial')

    def test_handover_failure_releases_task_gate(self):
        self.push('new')
        self.u.check()
        self.u.quiesce=lambda value:self.quiesced.append(value)
        self.busy=False
        with patch.object(self.u,'_handover',side_effect=OSError('test failure')):
            self.u.status['state']='waiting'
            self.u._wait_and_restart()
        self.assertEqual(self.quiesced,[False])
        self.assertEqual(self.u.state()['state'],'error')

if __name__=='__main__':
    unittest.main()
