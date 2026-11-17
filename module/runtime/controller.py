"""Single input owner: native Python tasks in a worker thread, original Lua tasks
inside the acquisition thread (sortie, until it is rewritten natively)."""
from collections import deque
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import time
import uuid

from module.legacy.vm import LegacyVM, identifier, text
from module.runtime.native import NATIVE_TASKS, NativeRun
from module.logger import atomic_json, now
from module.config.task_settings import read_tasks
from module.config.config import Config

SUPPORTED = ('expedition', 'sortie')
NAMES = {'expedition': '远征收取与继续派遣', 'sortie': '原方案C'}
SOURCES = {'expedition': 'native', 'sortie': 'original_lua_functions'}
EXPEDITION_MARGIN = timedelta(seconds=30)  # let the game flag the expedition finished
EXPEDITION_MIN = timedelta(minutes=1)


def clock(seconds):
    return f'{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}'


def chapter_summary(chapters):
    """'1 - · 2 0:30:12 · 3 0:35:53, ?1' for the chapters walked, first to last."""
    parts = []
    for index, (seconds, unreadable) in enumerate(chapters, 1):
        values = [clock(s) for s in seconds] + (['?%d' % unreadable] if unreadable else [])
        parts.append(f'{index} ' + (', '.join(values) or '-'))
    return ' · '.join(parts)


def next_run(current, interval_minutes, result):
    """(next run time, reason). Expeditions come back when the earliest fleet
    away returns, as read from the game's own countdowns; the configured
    interval is only a fallback when nothing was read."""
    fallback = current + timedelta(minutes=interval_minutes)
    remaining = getattr(result, 'remaining', None)
    unreadable = getattr(result, 'unreadable', 0)
    if remaining is None:
        return fallback, f'未读取远征倒计时，按间隔 {interval_minutes} 分钟'
    if not remaining:
        if unreadable:
            return fallback, f'{unreadable} 个远征倒计时无法识别，按间隔 {interval_minutes} 分钟'
        return fallback, f'没有进行中的远征，按间隔 {interval_minutes} 分钟'
    earliest = min(remaining)
    due = current + max(timedelta(seconds=earliest) + EXPEDITION_MARGIN, EXPEDITION_MIN)
    reason = (f'{len(remaining)} 支远征在外，最早的 '
              f'{earliest // 3600}:{earliest // 60 % 60:02d}:{earliest % 60:02d} 后结束')
    if unreadable and fallback < due:
        return fallback, reason + f'，但有 {unreadable} 个倒计时无法识别，按间隔 {interval_minutes} 分钟'
    return due, reason


class TaskController:
    def __init__(self, runtime):
        self.runtime = runtime
        self.vm = None
        self.native = None
        self.scheduler = False
        self.update_pending = False
        self.failures = {}
        self.due = self.load_due()
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
                                      'due': dict(self.due), 'source': SOURCES.get(self.result.get('task'), ''),
                                      'plan': 'legacy-C', 'running': self.busy}

    @property
    def busy(self):
        return self.vm is not None or self.native is not None

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
                folder=self.runtime.store.root/'screenshots'/'runs'/self.result['id']
                folder.mkdir(parents=True,exist_ok=True)
                (folder/f"{int(time.time()*1000)}.png").write_bytes(self.runtime.frame['png'])

    def start(self, task):
        if self.update_pending:
            raise ValueError('正在等待更新，暂不启动新任务')
        if self.busy:
            raise ValueError('已有任务持有当前设备，请先停止或等待完成')
        if task not in SUPPORTED:
            raise ValueError('目前接入远征和原方案C出征，其他任务尚未适配')
        if not self.runtime.serial or self.runtime.status != 'live':
            raise ValueError('请先连接舰R并恢复实时画面')
        self.runtime.adb.ensure_input_ready(self.runtime.serial)
        settings = read_tasks(self.runtime.store.root)[task]
        if task in NATIVE_TASKS:
            return self.start_native(task, settings)
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

    def start_native(self, task, settings):
        if self.runtime.emulator is None:
            raise ValueError('设备的截图/控制方式尚未初始化，请在设备设置中重新连接')
        run = NativeRun(self.runtime, task, settings, self.native_done)
        self.result = {'status': 'running', 'task': task, 'name': NAMES[task], 'page': '', 'action': '启动原生任务',
                       'inputs': 0, 'collected': 0, 'battles': 0, 'error': '',
                       'id': uuid.uuid4().hex, 'started': now(), 'settings': settings,
                       'methods': {'screenshot': self.runtime.emulator.config.Emulator_ScreenshotMethod,
                                   'control': self.runtime.emulator.config.Emulator_ControlMethod}}
        self.native = run
        self.runtime.store.event(f'原生任务 · 开始：{NAMES[task]}（截图 {self.result["methods"]["screenshot"]} · '
                                 f'控制 {self.result["methods"]["control"]}）')
        run.start()
        self.persist()

    def native_done(self, run, status):
        # Called from the worker thread.
        with self.runtime.lock:
            if run is not self.native:
                return
            self.native = None
            self.mirror(run)
            result = run.result
            if status == 'completed':
                self.failures.pop(self.result['task'], None)
                self.result['collected'] = getattr(result, 'collected', 0)
                self.result.update(status='completed', action='原生任务完成，已回港', ended=now())
                task = self.result['task']
                due, reason = next_run(datetime.now(timezone.utc), self.result['settings']['interval_minutes'], result)
                self.due[task] = due.isoformat()
                self.save_due()
                self.runtime.store.event(f'原生任务 · 完成：{NAMES[task]}，收取 {self.result["collected"]} 个远征；'
                                         f'下次 {due.astimezone().strftime("%m-%d %H:%M")}（{reason}）')
                if getattr(result, 'chapters', None):
                    self.runtime.store.event('原生任务 · 远征逐章读数：' + chapter_summary(result.chapters))
            elif status == 'stopped':
                self.result.update(status='stopped', action=run.error or '任务已停止', ended=now())
            else:
                self.result.update(status='fault', error=run.error, action='已停止输入', ended=now())
                if self.scheduler:
                    self.task_failed(self.result['task'], run.error)
                self.runtime.store.event('原生任务 · 停止：' + run.error, 'warning')
            self.persist()
        if status == 'fault':
            self.runtime.save_fault('原生任务停止：' + run.error[:300])
        self.runtime.wake.set()

    def mirror(self, run):
        self.result.update(page=run.page or self.result['page'], inputs=run.inputs,
                           action=run.last_action or self.result['action'])
        if run.worker is not None and getattr(run.worker, 'result', None) is not None:
            self.result['collected'] = run.worker.result.collected

    def control(self, action, task=''):
        if self.update_pending and action in ('start', 'scheduler-start'):
            raise ValueError('正在等待更新，暂不启动新任务')
        if action == 'start':
            self.start(task)
        elif action == 'scheduler-start':
            if not any(c['enabled'] for k,c in read_tasks(self.runtime.store.root).items() if k in SUPPORTED):
                raise ValueError('请先在远征或常用图配置中启用任务')
            self.scheduler = True
            self.failures.clear()
            self.runtime.auto_connect_enabled = True
            self.runtime.next_connect = 0
            self.save_due()
            self.event('调度器已启动' + ('' if self.runtime.serial else '，正在连接模拟器'))
        elif action == 'scheduler-stop':
            self.scheduler = False
            self.save_due()
            self.stop('调度器已停止')
        elif action == 'pause':
            if not self.busy:raise ValueError('当前没有运行任务')
            if self.native:self.native.paused.set()
            self.result['status'] = 'paused'
            self.event('已暂停，停止后续输入')
        elif action == 'resume':
            if not self.busy:raise ValueError('当前没有可恢复任务')
            if self.runtime.status != 'live':raise ValueError('请先恢复实时画面')
            if self.native:self.native.paused.clear()
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
        if self.native:
            # The worker stops at its next device call; it may finish an
            # in-flight screenshot/click but sends nothing afterwards.
            self.native.stop(message)
            self.native.paused.clear()
            self.result.update(status='stopping', action=message)
            self.event(message)
            self.persist()
            return
        self.vm = None
        self.touch = None
        self.result.update(status='stopped', action=message)
        self.event(message)
        self.persist()

    def load_due(self):
        """Next run times and the scheduler switch survive a restart or an
        update (data/scheduler.json), like AzurPilot resuming its task loop."""
        import json
        config = Config(self.runtime.store.root)
        try:
            data = config.section('Scheduler')
            self.scheduler = bool(data.get('Enable', False))
            return {k: v for k, v in data.get('NextRun', {}).items() if k in SUPPORTED and datetime.fromisoformat(v)}
        except (OSError, ValueError, AttributeError):
            return {}

    def save_due(self):
        Config(self.runtime.store.root).save_section('Scheduler', {'NextRun': self.due, 'Enable': self.scheduler})

    def task_failed(self, task, message):
        """A failed task is retried later instead of stopping the scheduler;
        three failures in a row stop it (the screen likely needs a human)."""
        self.failures[task] = self.failures.get(task, 0) + 1
        if self.failures[task] >= 3:
            self.scheduler = False
            self.event(f'{NAMES.get(task, task)} 连续失败 {self.failures[task]} 次，调度器已停止：{message[:200]}')
        else:
            self.due[task] = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
            self.event(f'{NAMES.get(task, task)} 失败（第 {self.failures[task]} 次），10 分钟后重试：{message[:200]}')
        self.save_due()

    def persist(self):
        atomic_json(self.runtime.store.root/'log'/'automation-last-run.json', self.state())

    def schedule(self):
        if not self.scheduler or self.busy or self.update_pending:return
        if not self.runtime.serial or self.runtime.status != 'live':return  # wait for the device
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
        self.save_due()
        self.event('完成：'+NAMES[task])
        self.vm=None;self.persist()

    def tick(self, raw):
        try:
            self.schedule()
            if self.native:
                self.mirror(self.native)
                return
            self.step(raw)
            if self.vm and self.result['status']=='running':
                self.result['battles']=int(self.vm.globals[identifier('战斗次数C')] or 0)
                limit=360 if '战斗' in self.result['page'] else 150
                if time.monotonic()-self.page_time>limit:
                    raise RuntimeError('原任务页面长期没有进展：'+self.result['page'])
        except Exception as exc:
            self.vm=None;self.touch=None
            if self.scheduler and self.result.get('task'):
                self.task_failed(self.result['task'], str(exc))
            self.result.update(status='fault',error=str(exc)[:700],action='已停止输入')
            self.event('停止：'+str(exc)[:500]);self.persist()
            self.runtime.save_fault('原任务停止：'+str(exc)[:300])
