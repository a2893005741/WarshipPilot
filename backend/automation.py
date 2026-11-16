"""Single input owner executing original Lua tasks inside the acquisition thread."""
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import time
import uuid

from .legacy_vm import LegacyVM, identifier, text
from .store import atomic_json, now
from .task_settings import read_tasks

SUPPORTED = ('expedition', 'sortie')
NAMES = {'expedition': '远征收取与继续派遣', 'sortie': '原方案C · 6-1 · 第二舰队'}


class TaskController:
    def __init__(self, runtime):
        self.runtime = runtime
        self.vm = None
        self.scheduler = False
        self.due = {}
        self.delay_until = 0.
        self.first_resume = True
        self.needs_frame = True
        self.touch = None
        self.clicks = deque(maxlen=50)
        self.page_time = time.monotonic()
        self.result = {'status': 'idle', 'task': '', 'name': '', 'page': '', 'action': '',
                       'inputs': 0, 'collected': 0, 'battles': 0, 'error': '', 'id': '', 'started': ''}

    def state(self):
        return deepcopy(self.result) | {'scheduler': self.scheduler, 'supported': list(SUPPORTED),
                                      'enabled': sum(v['enabled'] for k,v in read_tasks(self.runtime.store.root).items() if k in SUPPORTED),
                                      'due': dict(self.due), 'source': 'original_lua_functions',
                                      'plan': 'legacy-C', 'running': self.vm is not None}

    def event(self, message):
        self.runtime.store.event('原脚本 · ' + message)

    def page(self, value):
        if value != self.result['page']:
            self.result['page'] = value
            self.page_time = time.monotonic()
            self.event('当前页面：' + value)
            if value == '继续远征确认':
                self.result['collected'] += 1
            if self.result.get('settings',{}).get('save_screenshots') and self.runtime.frame:
                folder=self.runtime.store.root/'runs'/self.result['id']
                folder.mkdir(parents=True,exist_ok=True)
                (folder/f"{int(time.time()*1000)}.png").write_bytes(self.runtime.frame['png'])

    def start(self, task):
        if self.vm:
            raise ValueError('已有任务持有当前设备，请先停止或等待完成')
        if task not in SUPPORTED:
            raise ValueError('目前接入远征和原方案C出征，其他任务尚未适配')
        if not self.runtime.serial or self.runtime.status != 'live':
            raise ValueError('请先连接舰R并恢复实时画面')
        self.runtime.adb.ensure_input_ready(self.runtime.serial)
        settings = read_tasks(self.runtime.store.root)[task]
        if task == 'sortie' and (settings['stage'] not in ('','6-1') or settings['fleet'] != 2):
            raise ValueError('本轮实机选择是原方案C：6-1、第二舰队；请使用原方案参数')
        vm = LegacyVM(self.runtime.resources, self.runtime.store.root, task, settings, self.event, self.page)
        self.result = {'status': 'running', 'task': task, 'name': NAMES[task], 'page': '', 'action': '启动原函数',
                       'inputs': 0, 'collected': 0, 'battles': 0, 'error': '',
                       'id': uuid.uuid4().hex, 'started': now(), 'settings': settings}
        self.vm = vm
        self.first_resume = True
        self.needs_frame = True
        self.delay_until = 0
        self.touch = None
        self.clicks.clear()
        self.page_time = time.monotonic()
        self.event('开始：' + NAMES[task] + '；使用恢复的原Lua函数')
        self.persist()

    def control(self, action, task=''):
        if action == 'start':
            self.start(task)
        elif action == 'scheduler-start':
            if not any(c['enabled'] for k,c in read_tasks(self.runtime.store.root).items() if k in SUPPORTED):
                raise ValueError('请先在远征或常用图配置中启用任务')
            self.scheduler = True
            self.event('调度器已启动')
        elif action == 'scheduler-stop':
            self.scheduler = False
            self.stop('调度器已停止')
        elif action == 'pause':
            if not self.vm:raise ValueError('当前没有运行任务')
            self.result['status'] = 'paused'
            self.event('已暂停，停止后续输入')
        elif action == 'resume':
            if not self.vm:raise ValueError('当前没有可恢复任务')
            if self.runtime.status != 'live':raise ValueError('请先恢复实时画面')
            self.result['status'] = 'running'
            self.needs_frame = True
            self.page_time = time.monotonic()
            self.event('已恢复，重新读取当前画面')
        elif action == 'stop':
            self.scheduler = False
            self.stop('任务已停止')
        else:
            raise ValueError('未知任务控制操作')
        self.persist()
        self.runtime.wake.set()
        return self.state()

    def stop(self, message):
        self.vm = None
        self.touch = None
        self.result.update(status='stopped', action=message)
        self.event(message)
        self.persist()

    def persist(self):
        atomic_json(self.runtime.store.root/'automation-last-run.json', self.state())

    def schedule(self):
        if not self.scheduler or self.vm:return
        tasks=read_tasks(self.runtime.store.root)
        current=datetime.now(timezone.utc)
        local=datetime.now().strftime('%H:%M')
        ready=[(c['priority'],k) for k,c in tasks.items() if k in SUPPORTED and c['enabled'] and
               ((k not in self.due and local>=c['start_time']) or
                (k in self.due and datetime.fromisoformat(self.due[k]) <= current))]
        if ready:self.start(min(ready)[1])

    @staticmethod
    def screen_point(x, y):
        x,y=float(x),float(y)
        if not (0<=x<540 and 0<=y<960):raise ValueError(f'原函数输入坐标越界：{x},{y}')
        return round(y*1279/959), round((539-x)*719/539)

    def input(self, name, coordinates):
        # Recheck package ownership for each input, and bound repeated actions.
        self.runtime.adb.ensure_input_ready(self.runtime.serial)
        stamp=time.monotonic()
        key=(name, tuple(v//20 for v in coordinates))
        if sum(k==key and stamp-t<60 for t,k in self.clicks)>=10:
            raise RuntimeError('同一操作一分钟重复十次，已停止并保存现场')
        self.clicks.append((stamp,key))
        if name=='tap':self.runtime.adb.click(self.runtime.serial,*coordinates)
        else:self.runtime.adb.swipe(self.runtime.serial,*coordinates)
        self.result['inputs']+=1
        self.result['action']=name+' '+','.join(map(str,coordinates))
        self.event(self.result['action'])

    def step(self, raw):
        if not self.vm or self.result['status'] != 'running':return
        if time.monotonic()<self.delay_until:return
        if self.needs_frame:
            if raw is None:return
            self.vm.feed(raw)
            self.needs_frame=False
        inputs = 0
        for _ in range(30):
            result=self.vm.resume() if self.first_resume else self.vm.resume(0)
            self.first_resume=False
            if not isinstance(result,tuple):result=(result,)
            status,*values=result
            if status==b'dead':
                self.complete();return
            command,*args=values;command=int(command)
            if command==15:
                self.delay_until=time.monotonic()+max(0,float(args[0]))/1000
                self.result['action']=f'原函数等待 {int(float(args[0]))} ms'
                return
            if command==13:
                self.needs_frame=True
                self.result['action']='原函数请求新截图'
                return
            if command==65:
                self.input('tap',self.screen_point(*args[:2]))
                inputs += 1
                if inputs>=4:return
                continue
            if command==219:
                phase=int(args[0])
                if phase==0:self.touch={'start':self.screen_point(args[1],args[2])}
                elif phase==1:
                    if not self.touch:raise RuntimeError('原滑动缺少按下事件')
                    self.touch.update(end=self.screen_point(args[1],args[2]),duration=max(50,min(3000,int(args[4]))))
                elif phase==2:
                    if not self.touch or 'end' not in self.touch:raise RuntimeError('原滑动缺少移动事件')
                    self.input('swipe',(*self.touch['start'],*self.touch['end'],self.touch['duration']))
                    self.touch=None
                continue
            raise RuntimeError('未知原函数异步事件：'+str(command))
        # Yield the device lock so pause/stop can run between SDK bursts.

    def complete(self):
        self.result['battles']=int(self.vm.globals[identifier('战斗次数C')] or 0)
        task=self.result['task'];settings=self.result['settings']
        if self.result['page']!='港区':
            raise RuntimeError('原任务未回到母港，不能标记完成')
        if task=='sortie' and self.result['battles']<settings['runs']:
            raise RuntimeError('原函数已返回，但尚未达到出征次数，保留现场供核对')
        self.result.update(status='completed', action='原流程已回港，本轮完成', ended=now())
        self.due[task]=(datetime.now(timezone.utc)+timedelta(minutes=settings['interval_minutes'])).isoformat()
        self.event('完成：'+NAMES[task])
        self.vm=None;self.persist()

    def tick(self, raw):
        try:
            self.schedule()
            self.step(raw)
            if self.vm and self.result['status']=='running':
                self.result['battles']=int(self.vm.globals[identifier('战斗次数C')] or 0)
                limit=360 if '战斗' in self.result['page'] else 150
                if time.monotonic()-self.page_time>limit:
                    raise RuntimeError('原任务页面长期没有进展：'+self.result['page'])
        except Exception as exc:
            self.vm=None;self.scheduler=False;self.touch=None
            self.result.update(status='fault',error=str(exc)[:700],action='已停止输入')
            self.event('停止：'+str(exc)[:500]);self.persist()
            self.runtime.save_fault('原任务停止：'+str(exc)[:300])
