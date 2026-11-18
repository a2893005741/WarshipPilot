"""Rebuild ALAS-style task/argument definitions from the recovered original UI."""
from pathlib import Path
import json,re,yaml
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'module/config/argument'
OUT.mkdir(parents=True,exist_ok=True)
menu={
 'Warship':{'name':'舰R设置','tasks':{'general':['Runtime','Repair','Retirement','Drop','General'],'control':['Control']}},
 'DailyMission':{'name':'日常任务','tasks':{'expedition':['Scheduler','Expedition'],'campaign':['Scheduler','Campaign'],'exercise':['Scheduler','Exercise']}},
 'Farm':{'name':'出征方案','tasks':{'sortie_a':['Scheduler','Map','Fleet','Repair','Battle','Enemy','Sortie'],'sortie_b':['Scheduler','Map','Fleet','Repair','Battle','Enemy','Sortie'],'sortie':['Scheduler','Map','Fleet','Repair','Battle','Enemy','Sortie']}},
 'Decisive':{'name':'决战任务','tasks':{'decisive':['Scheduler','Decisive']}},
}
tasks={
 'general':{'name':'通用设置','executable':False,'help':'原脚本的修理、舰船处理与记录设置，保留配置供后续任务接入。'},
 'control':{'name':'功能控制台','executable':False,'help':'原脚本的前后方案与远征开关，保留配置供后续任务接入。'},
 'expedition':{'name':'远征','executable':True,'help':'收取已完成远征，并由原舰队继续派遣。'},
 'campaign':{'name':'战役','executable':False,'help':'保存原脚本战役参数；本版尚未接入执行。'},
 'exercise':{'name':'演习','executable':False,'help':'保存原脚本演习参数；本版尚未接入执行。'},
 'sortie_a':{'name':'方案 A','executable':False,'help':'保存原脚本方案 A 参数；本版尚未接入执行。'},
 'sortie_b':{'name':'方案 B','executable':False,'help':'保存原脚本方案 B 参数；本版尚未接入执行。'},
 'sortie':{'name':'方案 C','executable':True,'help':'使用原脚本方案 C 执行出征，修改的方案参数在下次任务启动时使用。'},
 'decisive':{'name':'决战','executable':True,'help':'使用原脚本决战。'},
}
labels={'Scheduler':'调度设置','Expedition':'远征设置','Campaign':'战役设置','Exercise':'演习设置','Map':'关卡与路线','Fleet':'舰队与换船','Repair':'修理设置','Battle':'节点与阵型','Enemy':'敌舰判断','Sortie':'出征设置','Runtime':'运行与限制','Retirement':'拆船与强化','Drop':'捞船与截图','General':'其他设置','Control':'方案控制','Decisive':'决战设置'}
args={task:{} for task in tasks}
scheduler={
 'Enable':{'name':'启用任务','type':'checkbox','value':False,'storage':'task','key':'enabled'},
 'Priority':{'name':'优先级','help':'数字越小，优先级越高。','type':'number','value':5,'min':1,'max':10,'storage':'task','key':'priority'},
 'StartTime':{'name':'计划时间','type':'time','value':'00:00','storage':'task','key':'start_time'},
 'IntervalMinutes':{'name':'执行间隔（分钟）','type':'number','value':60,'min':1,'max':10080,'storage':'task','key':'interval_minutes'},
 'NextRun':{'name':'下次运行','type':'datetime-local','value':'','storage':'scheduler','key':'NextRun'},
 'Runs':{'name':'执行次数','type':'number','value':1,'min':1,'max':9999,'storage':'task','key':'runs'},
 'SaveScreenshots':{'name':'保留任务截图','type':'checkbox','value':True,'storage':'task','key':'save_screenshots'},
}
for task in tasks:
 if task not in ('general','control'):
  args[task]['Scheduler']=json.loads(json.dumps(scheduler))
  if not tasks[task]['executable']:
   for field in args[task]['Scheduler'].values():field['display']='readonly'
 if task=='expedition':
  args[task]['Expedition']={'Dispatch':{'name':'派遣方式','type':'input','value':'继续原舰队远征','display':'readonly','storage':'constant'}}
def group_for(key,task):
 if task in ('campaign','exercise','decisive','control'):return {'campaign':'Campaign','exercise':'Exercise','decisive':'Decisive','control':'Control'}[task]
 if task.startswith('sortie'):
  if key.startswith('满级') or '编队' in key or '舰队' in key:return 'Fleet'
  if any(k in key for k in ('快修','泡澡','慢修')):return 'Repair'
  if re.search('([一二三四五六七]战|第[一二三四五六七]点)',key):return 'Battle'
  if any(k in key for k in ('判断','转单横','转轮型','远程打击','索敌')):return 'Enemy'
  if any(k in key for k in ('自定义','章','图','入口','终点','炸鱼','偷油','偷弹','偷铝','偷钢','胖次','避轻母','避战巡','只打','不打','练鱼')):return 'Map'
  return 'Sortie'
 if any(k in key for k in ('拆','强化','狗粮','养成')):return 'Retirement'
 if any(k in key for k in ('捞','图鉴','截图')):return 'Drop'
 if any(k in key for k in ('修','泡澡')):return 'Repair'
 if any(k in key for k in ('限制','休息','重启','日志','顶号')):return 'Runtime'
 return 'General'
inventory=json.loads((ROOT/'assets/legacy-fields.json').read_text(encoding='utf-8'))
defaults=json.loads((ROOT/'assets/legacy/task-defaults.json').read_text(encoding='utf-8'))
count=0
for field in inventory['fields']:
 key=field['legacy_key'];page=field['page']
 if key not in defaults or re.search('注册码|密码|账号|帐号|token|密钥|邮箱|手机|SPT|包名|IOS|配置文件',key,re.I):continue
 task={'方案A':'sortie_a','方案B':'sortie_b','方案C':'sortie'}.get(page)
 if not task:
  task='campaign' if key.startswith('战役') else 'exercise' if key.startswith('演习') else 'decisive' if key.startswith('决战') or key in ['肌肉记忆','关键一击','黑科技','长跑训练','抱头蹲防','满编后买经验','教官用技能','U47','U81','换票资源','351','U96','U1206','鹦鹉螺','U1405','鲃鱼','开局SL潜艇'] else 'control' if page=='功能控制台' else 'general'
 group=group_for(key,task);value=defaults[key]
 entry={'name':re.sub('[ABC]$','',key) if page.startswith('方案') else key,'type':'checkbox' if isinstance(value,bool) else 'number' if isinstance(value,int) else 'input','value':value,'storage':'legacy','key':key,'source':{'page':page,'ui_line':field['ui_definition_line']}}
 options=field.get('legacy_options_in_order')
 if options:entry.update(type='select',option=[{'value':i,'label':s} for i,s in enumerate(options)])
 if key in ('大破出征C','大破进击C'):
  entry.update(value=False,display='readonly',help='本版固定关闭。')
 args[task].setdefault(group,{})[key]=entry;count+=1
# Only keep groups that really have options.
for group in menu.values():
 for task in group['tasks']:group['tasks'][task]=[name for name in group['tasks'][task] if name in args[task]]
for name,value in [('task.yaml',{'menu':menu,'tasks':tasks}),('argument.yaml',args),('gui.yaml',labels),('default.yaml',{}),('override.yaml',{})]:
 (OUT/name).write_text(yaml.safe_dump(value,allow_unicode=True,sort_keys=False),encoding='utf-8')
print('Original business fields:',count)
