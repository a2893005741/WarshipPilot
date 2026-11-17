"""Execute the recovered original Lua functions through a desktop SDK adapter.

Task branches, coordinates, touch sequences and delays remain in main.lua52.luac.
The adapter implements the old engine's platform operations; it has no task routes.
"""
from datetime import datetime
import json
from pathlib import Path
import random
import re
import time

import cv2
import numpy as np
from lupa.lua52 import LuaRuntime

from module.vision.color import _scan_order


def identifier(name):
    return ('id' + name.encode().hex()).encode()


def text(value):
    return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else str(value)


# Desktop task -> original global function used as the entry point.
ENTRIES = {'sortie': '出征战斗', 'campaign': '打战役', 'exercise': '打演习', 'reward': '收任务'}
PHYSICAL = (720, 1280)  # portrait size of the 1280x720 game frame (old GetScreen)
CANVAS = (540, 960)     # the script's default canvas


class LegacyVM:
    def __init__(self, resources: Path, data: Path, task: str, settings: dict, log, page_changed):
        if task not in ENTRIES:
            raise ValueError(f'原脚本没有对应的任务入口：{task}')
        self.task = task
        self.resources, self.data = resources, data
        self.log, self.page_changed = log, page_changed
        self.started = time.monotonic()
        self.image = None
        self.patterns = {}
        self.search_images = {}
        self.speed_notice = False
        self.exercise_completed = False
        self.canvas = CANVAS
        self.physical = False  # GetScreen answers the physical size (战役剩余次数 only)
        def template(name):
            return cv2.imdecode(np.frombuffer((resources/'assets/game'/name).read_bytes(),np.uint8),cv2.IMREAD_COLOR)
        self.continue_templates = [(390,190,template('expedition-continue-title.png')),
                                   (515,315,template('expedition-continue-question.png'))]
        self.config = json.loads((resources / 'assets/legacy/task-defaults.json').read_text(encoding='utf-8'))
        self.config.update(settings.get('legacy', {}))
        self.config.update({'前方案A': False, '前方案B': False,
                            '前方案C': True, '后方案A': False, '后方案B': False, '后方案C': False,
                            '网络日志': False, '保持加速': False, '大破出征C': False, '大破进击C': False,
                            '战役开关': False, '演习开关': False})
        if task == 'sortie':
            # Original code stops when count > limit (not >=). Keep that branch
            # and translate the desktop target count to its existing threshold.
            self.config['战斗次数限制'] = str(int(settings.get('runs', 1))-1)
        if task == 'campaign':
            # 打战役 runs only with its switch on. Its SL kills and restarts the
            # game (KillApp/RunApp), which the desktop build does not do.
            self.config.update({'战役开关': True, '战役SL': False})
        if task == 'exercise':
            # The desktop scheduler owns the switch; a manual run also runs
            # when scheduling is disabled. Fleet/formation remain original enums.
            self.config['演习开关'] = True
        self.lua = LuaRuntime(encoding=None, unpack_returned_tuples=True, register_eval=False,
                              register_builtins=False, max_memory=64_000_000)
        self.lua.execute((resources / 'assets/legacy/main.lua52.luac').read_bytes())
        self.globals = self.lua.globals()
        for key, value in json.loads((resources / 'assets/legacy/global-defaults.json').read_text()).items():
            self.globals[key.encode()] = value.encode() if isinstance(value, str) else value
        for name, value in {'现在方案': 'C', '回港': 0, '试用': 1, '心跳时间戳': 0, '渠道服': '',
                            '点击时间点': -10000, 'X暂存': -1, 'Y暂存': -1,
                            '有用': 1, '上次养成记录': 0, '战斗次数C': 0, '快修次数C': 0}.items():
            self.globals[identifier(name)] = value.encode() if isinstance(value, str) else value
        self.globals[identifier('TABLE')] = self.lua.table_from({
            '养成记录'.encode(): 0, '日期'.encode(): datetime.now().strftime('%Y%m%d').encode(),
            '决战BOSS次数'.encode(): 0})
        self.globals[b'host_sdk'] = self.sdk
        self.globals[b'host_page'] = lambda value: self.page_changed(text(value)) if value is not None else None
        self.globals[b'host_continue'] = self.expedition_continue
        self.globals[b'host_split'] = lambda value,separator: self.lua.table_from(value.split(separator))
        self.lua.execute(b'''
            LuaAuxLib = {TableSize=function(t) local n=0 for _ in pairs(t) do n=n+1 end return n end,
                         StringSplit=host_split}
            LuaAuxLib.LuaAuxLid = function(cmd, ...)
                if cmd == 13 or cmd == 15 or cmd == 65 or cmd == 219 then
                    return coroutine.yield(cmd, ...)
                end
                return host_sdk(cmd, ...)
            end
        ''')
        # DateTime and file access are platform services, not game navigation.
        dates = {b'Year': '%Y', b'Month': '%m', b'Day': '%d', b'Hour': '%H', b'Minute': '%M', b'Second': '%S'}
        for key, fmt in dates.items():
            self.globals[b'DateTime'][key] = lambda fmt=fmt: int(datetime.now().strftime(fmt))
        self.globals[b'ShanHai'][b'RndEx'] = lambda low,high: random.randint(int(low),int(high))
        self.globals[b'File'][b'Read'] = self.read_file
        self.globals[b'File'][b'Write'] = self.write_file
        self.globals[b'Cjson'][b'Encode'] = lambda value: json.dumps(self.from_lua(value), ensure_ascii=False).encode()
        self.globals[b'Cjson'][b'Decode'] = lambda value: self.to_lua(json.loads(text(value)))
        # Preserve original recognition; handle only the newer expedition dialog.
        page_source = b'''
            local original = ''' + identifier('现在画面') + b'''
            ''' + identifier('现在画面') + b''' = function(...)
                if host_continue() then
                    host_page('EXPEDITION_CONTINUE')
                    ''' + identifier('固定延时点击') + b'''(198, 368, 700)
                    LuaAuxLib.LuaAuxLid(13, true)
                end
                local value = original(...)
                host_page(value)
                return value
            end
        '''
        for marker,value in {'EXPEDITION_CONTINUE':'继续远征确认'}.items():
            page_source=page_source.replace(marker.encode(),value.encode())
        self.lua.execute(page_source)
        # 战役剩余次数 asks the physical screen width (720 on this frame) and
        # switches the canvas to it for its digit pattern. Elsewhere GetScreen
        # keeps its established answer, which sortie's tap centres rely on.
        self.globals[b'host_physical'] = self.set_physical
        self.lua.execute(b'''
            local original = ''' + identifier('战役剩余次数') + b'''
            ''' + identifier('战役剩余次数') + b''' = function(...)
                host_physical(true)
                local result = table.pack(pcall(original, ...))
                host_physical(false)
                if not result[1] then error(result[2], 0) end
                return table.unpack(result, 2, result.n)
            end
        ''')
        # The original sortie returns when expedition rewards are ready or the
        # configured battle limit changes its plan to expedition-only mode.
        # Run the original collection function to return home, then finish.
        entry = self.globals[identifier(ENTRIES[task])]
        if task == 'exercise':
            # 打演习时间戳 is set on ENTRY, not on completion. Only the normal
            # two-pages-exhausted/home return clears 演习关闭加速. An ineligible
            # early return must not be mistaken for a completed run.
            self.globals[b'host_exercise_done'] = lambda: setattr(self, 'exercise_completed', True)
            entry = self.lua.eval(b'''function(exercise)
                return function()
                    local eligible = ''' + identifier('打演习时间戳') + b''' == 0
                        and LuaAuxLib.LuaAuxLid(193, ''' + repr('演习开关').encode() + b''') == true
                    exercise()
                    if eligible and ''' + identifier('演习关闭加速') + b''' == 0 then
                        host_exercise_done()
                    end
                end
            end''')(entry)
        if task == 'sortie':
            entry_source = b'''function(collect, sortie)
                return function()
                    while true do
                        sortie()
                        local waiting = ''' + identifier('现在方案') + b''' == 'WAIT_PLAN'
                        collect()
                        if waiting then return end
                    end
                end
            end'''
            entry = self.lua.eval(entry_source.replace(b'WAIT_PLAN', '挂远征'.encode()))(
                self.globals[identifier('收远征')], self.globals[identifier('出征战斗')])
        self.resume = self.lua.eval(b'''
            function(f)
                local t = coroutine.create(f)
                local function budget() error('Original task exceeded instruction budget') end
                return function(...)
                    debug.sethook(t, budget, '', 1000000)
                    local result = table.pack(coroutine.resume(t, ...))
                    if not result[1] then error(result[2]) end
                    return coroutine.status(t), table.unpack(result, 2, result.n)
                end
            end
        ''')(entry)
        for name in [b'execute', b'exit', b'remove', b'rename', b'getenv', b'tmpname']:
            self.globals[b'os'][name] = None
        for name in [b'io', b'package', b'require', b'dofile', b'loadfile']:
            self.globals[name] = None

    def feed(self, raw):
        bgr = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if bgr is None or bgr.shape[:2] != (720, 1280):
            raise ValueError('原脚本适配当前仅支持1280×720舰R画面')
        self.image = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        self.search_images.clear()

    def expedition_continue(self):
        # This confirmation was added after the recovered script version. Match
        # both its unique title and question, then use the original click helper.
        for x,y,template in self.continue_templates:
            if template is None:return False
            h,w=template.shape[:2]
            patch=cv2.cvtColor(self.image[y:y+h,x:x+w], cv2.COLOR_RGB2BGR)
            if float(cv2.matchTemplate(patch,template,cv2.TM_CCOEFF_NORMED)[0,0])<.96:return False
        return bool(np.all(np.abs(self.image[445,450].astype(int)-[231,194,32])<35))

    def set_physical(self, value):
        self.physical = bool(value)

    def pixel(self, x, y):
        x, y = int(round(float(x))), int(round(float(y)))
        w, h = self.canvas
        if not (0 <= x < w and 0 <= y < h):
            raise ValueError(f'原脚本坐标越界：{x},{y}（画布 {w}x{h}）')
        # Same endpoint transform used to verify the original extracted patterns;
        # a 720x1280 canvas maps 1:1 onto the 1280x720 frame.
        return self.image[round((w-1-x)*719/(w-1)), round(y*1279/(h-1))].astype(np.int16)

    @staticmethod
    def colors(value):
        result = []
        for alternative in text(value).split('|'):
            pieces = alternative.split('-')
            if not re.fullmatch('[0-9a-fA-F]{6}', pieces[0]):
                raise ValueError('原脚本颜色表达式需要核对：' + alternative)
            color = np.array([int(pieces[0][i:i+2], 16) for i in (4, 2, 0)], dtype=np.int16)
            tolerance = np.array([int(pieces[1][i:i+2], 16) for i in (4, 2, 0)], dtype=np.int16) if len(pieces)>1 else np.zeros(3, np.int16)
            result.append((color, tolerance))
        return result

    def compare(self, x, y, color, similarity):
        actual = self.pixel(x, y)
        tolerance = round((1-float(similarity))*255) + 2  # Two RGB levels for scaled-frame quantization.
        return any(np.all(np.abs(actual-expected) <= np.maximum(extra, tolerance)) for expected,extra in self.colors(color))

    def points(self, expression, similarity):
        expression = text(expression)
        if expression not in self.patterns:
            parsed=[]
            for point in expression.split(','):
                x,y,color=point.split('|',2)
                parsed.append((float(x),float(y),color))
            self.patterns[expression]=parsed
        return all(self.compare(x,y,color,similarity) for x,y,color in self.patterns[expression])

    def find_colors(self, x1, y1, x2, y2, color, offsets, direction, similarity):
        w, h = self.canvas
        x1,y1,x2,y2=map(lambda v:int(round(float(v))), (x1,y1,x2,y2))
        if (x1,y1,x2,y2) == (0,0,0,0):
            x2,y2=w-1,h-1
        x1,x2=sorted((x1,x2));y1,y2=sorted((y1,y2))
        x1,y1=max(0,x1),max(0,y1);x2,y2=min(w-1,x2),min(h-1,y2)
        if x2<x1 or y2<y1:return -1,-1
        # Use the same endpoint mapping as pixel(), including on the temporary
        # 720x1280 canvas used by 演习是否有潜艇 (its sixth slot is below y=960).
        if self.canvas not in self.search_images:
            columns=np.rint(np.arange(w)*(719/(w-1))).astype(int)
            rows=np.rint(np.arange(h)*(1279/(h-1))).astype(int)
            self.search_images[self.canvas]=self.image[719-columns[None,:],rows[:,None]]
        portrait=self.search_images[self.canvas]
        image=portrait[y1:y2+1,x1:x2+1].astype(np.int16)
        tolerance=round((1-float(similarity))*255) + 2
        mask=np.zeros(image.shape[:2],bool)
        for expected,extra in self.colors(color):
            mask|=np.all(np.abs(image-expected)<=np.maximum(extra,tolerance),axis=2)
        ys,xs=np.where(mask)
        xs=xs+x1;ys=ys+y1
        if offsets and text(offsets) not in ('','nil'):
            for point in text(offsets).split(','):
                dx,dy,c=point.split('|',2);xx=xs+int(float(dx));yy=ys+int(float(dy))
                keep=(xx>=0)&(xx<w)&(yy>=0)&(yy<h)
                xx=np.clip(xx,0,w-1);yy=np.clip(yy,0,h-1)
                actual=portrait[yy,xx].astype(np.int16);passed=np.zeros(len(xs),bool)
                for expected,extra in self.colors(c):passed|=np.all(np.abs(actual-expected)<=np.maximum(extra,tolerance),axis=1)
                keep&=passed;xs,ys=xs[keep],ys[keep]
        if not len(xs):return -1,-1
        # Share the original scan order with native tasks. Exercise uses 2
        # (bottom/right first); only sampling/colour compatibility stays in VM.
        order=_scan_order(xs,ys,int(direction),(x1+x2)/2,(y1+y2)/2)
        index=order[0];return int(xs[index]),int(ys[index])

    def sdk(self, command, *args):
        command=int(command)
        if command==10:
            if args and args[0] is not None:self.log(text(args[0])[:500])
            return 0
        if command==74:
            self.log(' '.join(text(value) for value in args if value is not None)[:500])
            return 0
        if command==84:return int((time.monotonic()-self.started)*1000)
        if command==29:return 180  # Virtual SDK canvas: 540x960, scaled from the actual frame.
        if command==44:
            # GetScreen(axis). Established answer 540 for every caller except
            # 战役剩余次数, which compares it with the physical width.
            return PHYSICAL[1 if args and int(args[0] or 0) else 0] if self.physical else 540
        if command==191:
            # SetScreenScale(0, width, height): canvas for later colour checks.
            if len(args)>=3 and args[1] is not None and args[2] is not None:
                size=(int(args[1]),int(args[2]))
                if size not in (CANVAS,PHYSICAL):
                    raise RuntimeError(f'原脚本请求的画布 {size[0]}x{size[1]} 与 1280×720 画面不符')
                self.canvas=size
                return 0
            return 960
        if command in (177,222):
            # KillApp / RunApp: the original restarts the game (SL, frozen screen).
            raise RuntimeError('原脚本请求结束并重启游戏（'+text(args[0] if args else '')+'），桌面版不自动重启，已停止并保留现场')
        if command==193:
            value=self.config.get(text(args[0]), '')
            return value.encode() if isinstance(value,str) else value
        if command==229:return 1 if self.points(args[0],args[1] if len(args)>1 else .9) else 0
        if command==2:return 0 if self.compare(*args[:4]) else -1
        if command in (1,119):return ''.join(f'{v:02X}' for v in self.pixel(*args[:2])[::-1]).encode()
        if command==66:return self.find_colors(*args[:8])
        if command==168:
            x1,y1,x2,y2,color,direction,similarity=args[:7]
            return self.find_colors(x1,y1,x2,y2,color,b'',direction,similarity)
        if command==138:return b'com.huanmeng.zhanjian2'
        if command==207:return text(args[0]).find(text(args[1]))+1
        if command==94:
            # Old CInt conversion used for numeric text controls.
            return int(float(text(args[0])))
        if command==88:
            # SetAppSpeed is an Android engine service. Desktop deliberately runs
            # at the game's normal speed; do not inject the old speed plugin.
            if not self.speed_notice:
                self.log('旧引擎变速接口使用游戏原速；原点击、滑动和延时继续执行')
                self.speed_notice = True
            return 0
        raise RuntimeError(f'原脚本运行接口尚未适配：{command}，参数：{str([text(a) for a in args])[:240]}')

    def to_lua(self, value):
        if isinstance(value,dict):return self.lua.table_from({text(k).encode():self.to_lua(v) for k,v in value.items()})
        if isinstance(value,list):return self.lua.table_from([self.to_lua(v) for v in value])
        return value.encode() if isinstance(value,str) else value

    def from_lua(self, value):
        if hasattr(value,'items'):return {text(k):self.from_lua(v) for k,v in value.items()}
        return text(value) if isinstance(value,bytes) else value

    def read_file(self, filename):
        file=self.file_path(filename)
        return file.read_bytes() if file.is_file() else None

    def write_file(self, filename, content):
        file=self.file_path(filename);file.parent.mkdir(parents=True,exist_ok=True)
        file.write_bytes(content if isinstance(content,bytes) else text(content).encode())
        return True

    def file_path(self, filename):
        name=Path(text(filename).replace('\\','/')).name
        if not name or re.search('账号|注册|密码|token',name,re.I):raise ValueError('不迁移旧平台的账户文件')
        return self.data/'log'/'legacy-files'/name
