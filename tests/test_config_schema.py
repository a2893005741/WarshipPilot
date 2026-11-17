"""Generated original-script options and ALAS task/group/argument persistence."""
from pathlib import Path
import json
import tempfile
import unittest
from module.config.config import Config
from module.config.schema import schema,save_field,config_values
from module.config.task_settings import TaskDraft,read_tasks,save_task,normalize_tasks
from module.legacy.vm import LegacyVM

ROOT=Path(__file__).resolve().parents[1]

def field_path(task,key):
    for group,fields in schema()['args'][task].items():
        if key in fields:return f'{task}.{group}.{key}'
    raise KeyError(key)

class SchemaTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def test_original_enum_order_and_defaults_are_preserved(self):
        inventory=json.loads((ROOT/'assets/legacy-fields.json').read_text(encoding='utf-8'))
        original={f['legacy_key']:f for f in inventory['fields']}
        count=0
        for groups in schema()['args'].values():
            for fields in groups.values():
                for field in fields.values():
                    if field['storage']!='legacy':continue
                    count+=1
                    expected=original[field['key']].get('legacy_options_in_order')
                    if expected:self.assertEqual([o['label'] for o in field['option']],expected)
        self.assertEqual(count,506)

    def test_save_original_option_in_grouped_config_and_reload(self):
        path=field_path('sortie','出征舰队C')
        save_field(self.root,path,0)
        self.assertEqual(Config(self.root).section('Tasks')['sortie']['Fleet']['出征舰队C'],0)
        self.assertEqual(read_tasks(self.root)['sortie']['legacy']['出征舰队C'],0)
        self.assertEqual(config_values(self.root,'sortie')['values']['Fleet']['出征舰队C'],0)

    def test_old_task_config_normalizes_without_losing_schedule_or_parameters(self):
        c=Config(self.root);c.save_section('Tasks',{'expedition':{'enabled':True,'priority':2,'interval_minutes':90},'sortie':{'runs':7}})
        c.save_section('Scheduler',{'Enable':True,'NextRun':{'expedition':'2030-01-01T00:00:00+00:00'}})
        normalize_tasks(self.root)
        self.assertTrue(read_tasks(self.root)['expedition']['enabled'])
        self.assertEqual(read_tasks(self.root)['expedition']['interval_minutes'],90)
        self.assertEqual(read_tasks(self.root)['sortie']['runs'],7)
        self.assertEqual(c.section('Tasks')['expedition']['Scheduler']['NextRun'],'2030-01-01T00:00:00+00:00')
        before=c.instance_file.read_bytes();normalize_tasks(self.root);self.assertEqual(before,c.instance_file.read_bytes())

    def test_invalid_enum_and_cross_task_or_private_fields_are_rejected(self):
        with self.assertRaises(ValueError):save_field(self.root,field_path('sortie','出征舰队C'),999)
        with self.assertRaises(ValueError):save_task(self.root,'expedition',TaskDraft(legacy={'出征舰队C':0}))
        with self.assertRaises(ValueError):save_task(self.root,'general',TaskDraft(legacy={'SPT':'not-a-real-token'}))
        with self.assertRaises(ValueError):save_field(self.root,'sortie.Scheduler.Enable','true')

    def test_readonly_safety_and_unimplemented_schedule_are_rejected(self):
        with self.assertRaises(ValueError):save_field(self.root,field_path('sortie','大破出征C'),True)
        with self.assertRaises(ValueError):save_field(self.root,'exercise.Scheduler.Enable',True)
        with self.assertRaises(ValueError):save_field(self.root,field_path('campaign','战役SL'),True)

    def test_campaign_and_reward_schedules_are_editable(self):
        save_field(self.root,'campaign.Scheduler.Enable',True)
        save_field(self.root,'reward.Scheduler.Enable',True)
        tasks=read_tasks(self.root)
        self.assertTrue(tasks['campaign']['enabled'] and tasks['reward']['enabled'])
        self.assertEqual((tasks['campaign']['start_time'],tasks['reward']['interval_minutes']),('00:10',30))

    def test_next_run_updates_group_and_live_scheduler_document(self):
        normalize_tasks(self.root)
        save_field(self.root,'expedition.Scheduler.NextRun','2030-01-01T08:00:00+08:00')
        c=Config(self.root);due=c.section('Scheduler')['NextRun']['expedition']
        self.assertEqual(c.section('Tasks')['expedition']['Scheduler']['NextRun'],due)
        c.save_section('Scheduler',{'Enable':True,'NextRun':{'expedition':'2031-01-01T00:00:00+00:00'}})
        self.assertEqual(c.section('Tasks')['expedition']['Scheduler']['NextRun'],'2031-01-01T00:00:00+00:00')

    def test_vm_consumes_saved_original_options_and_keeps_fixed_safety(self):
        vm=LegacyVM(ROOT,self.root,'sortie',{'runs':3,'legacy':{'出征舰队C':0,'快修输入框C':'2','大破出征C':True,'大破进击C':True}},lambda *a:None,lambda *a:None)
        self.assertEqual(vm.config['出征舰队C'],0)
        self.assertEqual(vm.config['快修输入框C'],'2')
        self.assertEqual(vm.config['战斗次数限制'],'2')
        self.assertFalse(vm.config['大破出征C'])
        self.assertFalse(vm.config['大破进击C'])

if __name__=='__main__':unittest.main()
