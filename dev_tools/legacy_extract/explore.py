"""Enumerate every decision path of an original Lua function (dev tool).

The recovered bytecode is executed with a recording SDK: every recognition
call (CmpColorEx/CmpColor/FindMultiColor/FindColor) becomes a decision whose
outcome is forced. A depth-first search over the outcomes yields, for each
path, the full ordered list of recognition checks with their required result,
and the taps/swipes/waits the function emits on that path.

Nothing here touches a device or the game. Output is plain JSON consumed by
build_assets.py.

    uv run python dev_tools/legacy_extract/explore.py 现在画面 out.json
"""
from datetime import datetime
import json
from pathlib import Path
import sys
import time

from lupa.lua52 import LuaRuntime

ROOT = Path(__file__).resolve().parents[2]
LEGACY = ROOT / 'assets' / 'legacy'
DECISIONS = {229: 'points', 2: 'color', 66: 'find_multi', 168: 'find'}


def identifier(name):
    return ('id' + name.encode().hex()).encode()


def text(value):
    return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else value


class PathLimit(Exception):
    pass


class Explorer:
    def __init__(self, max_decisions=400, useful=1):
        self.max_decisions = max_decisions
        self.config = json.loads((LEGACY / 'task-defaults.json').read_text(encoding='utf-8'))
        self.lua = LuaRuntime(encoding=None, unpack_returned_tuples=True, register_eval=False)
        self.lua.execute((LEGACY / 'main.lua52.luac').read_bytes())
        g = self.globals = self.lua.globals()
        for key, value in json.loads((LEGACY / 'global-defaults.json').read_text()).items():
            g[key.encode()] = value.encode() if isinstance(value, str) else value
        for name, value in {'现在方案': 'C', '回港': 0, '试用': 1, '心跳时间戳': 0, '点击时间点': -10000,
                            'X暂存': -1, 'Y暂存': -1, '有用': useful, '上次养成记录': 0,
                            '战斗次数C': 0, '快修次数C': 0}.items():
            g[identifier(name)] = value.encode() if isinstance(value, str) else value
        g[b'host_sdk'] = self.sdk
        self.lua.execute(b'''
            LuaAuxLib = {TableSize=function(t) local n=0 for _ in pairs(t) do n=n+1 end return n end,
                         StringSplit=function(s, sep) local r={} for p in string.gmatch(s, "([^"..sep.."]+)") do r[#r+1]=p end return r end}
            LuaAuxLib.LuaAuxLid = function(cmd, ...) return host_sdk(cmd, ...) end
        ''')
        for key, fmt in {b'Year': '%Y', b'Month': '%m', b'Day': '%d', b'Hour': '%H', b'Minute': '%M', b'Second': '%S'}.items():
            g[b'DateTime'][key] = lambda fmt=fmt: int(datetime(2026, 1, 1, 12).strftime(fmt))
        g[b'ShanHai'][b'RndEx'] = lambda low, high: (int(low) + int(high)) // 2  # centre of random jitter
        g[b'File'][b'Read'] = lambda name: None
        g[b'File'][b'Write'] = lambda name, content: True
        # Snapshot globals so every path starts from identical state.
        self.lua.execute(b'__snapshot = {} for k, v in pairs(_G) do __snapshot[k] = v end')
        self.restore = self.lua.eval(b'''function()
            for k in pairs(_G) do if __snapshot[k] == nil and k ~= "__snapshot" then _G[k] = nil end end
            for k, v in pairs(__snapshot) do _G[k] = v end
        end''')
        self.runner = self.lua.eval(b'''function(f)
            local function budget() error("PATH_BUDGET") end
            debug.sethook(budget, "", 2000000)
            local ok, value = pcall(f)
            debug.sethook()
            return ok, value
        end''')

    # -- recording SDK -------------------------------------------------
    def sdk(self, command, *args):
        command = int(command)
        args = [text(a) for a in args]
        if command in DECISIONS:
            # Static-frame model: one recognition pass sees one screenshot, so
            # an identical query always gets the same answer on a path.
            key = json.dumps([command, args], ensure_ascii=False)
            if key in self.seen:
                index = self.seen[key]
                hit = self.decisions[index]['hit']
            else:
                index = len(self.decisions)
                if index >= self.max_decisions:
                    raise PathLimit('decision budget')
                check = json.dumps([DECISIONS[command], args], ensure_ascii=False)
                if check in self.forced_keys:
                    answer = self.decide(command, args, index, self.forced_keys[check])
                else:
                    answer = self.decide(command, args, index)
                self.seen[key] = index
                self.decisions.append({'kind': DECISIONS[command], 'args': args,
                                       'hit': answer is not None and answer is not False, 'answer': answer})
            self.trace.append(('check', index))
            self.steps += 1
            if self.steps > 5000:
                raise PathLimit('loop on static frame')
            answer = self.decisions[index]['answer']
            if command == 229:
                return 1 if answer else 0
            if command == 2:
                return -1 if answer is None else answer
            if command == 66:
                return (-1, -1) if answer is None else tuple(answer)
            if command == 168:
                return (-1, -1, -1) if answer is None else (*answer, 0)
        if command == 65:
            self.trace.append(('tap', [float(args[0]), float(args[1])]))
            return 0
        if command == 219:
            self.trace.append(('touch', args[:5]))
            return 0
        if command == 15:
            self.clock += float(args[0])
            self.trace.append(('wait', float(args[0])))
            return 0
        if command == 13:
            self.trace.append(('capture', None))
            return 0
        if command in (10, 74):
            message = ' '.join(str(a) for a in args if a is not None)
            self.trace.append(('log', message[:200]))
            return 0
        if command == 84:
            self.clock += 50
            return int(self.clock)
        if command == 29:
            return 180
        if command == 44:
            return 540 if str(args[0]) in ('0', '0.0') else 960
        if command == 191:
            return 0
        if command == 193:
            key = str(args[0])
            self.config_reads.add(key)
            value = self.config.get(key, '')
            return value.encode() if isinstance(value, str) else value
        if command in (1, 119):
            return b'000000'
        if command == 138:
            return b'com.huanmeng.zhanjian2'
        if command == 207:
            return str(args[0]).find(str(args[1])) + 1
        if command == 94:
            return int(float(str(args[0])))
        if command == 88:
            return 0
        self.trace.append(('unsupported', [command] + [str(a)[:80] for a in args]))
        raise PathLimit(f'unsupported sdk {command}')

    def decide(self, command, args, index, hit=None):
        """Forced outcome: None/False = miss; True/0/(x, y) = hit."""
        if hit is None:
            hit = self.forced[index] if index < len(self.forced) else False
        if not hit:
            return None if command != 229 else False
        if command == 229:
            return True
        if command == 2:
            return 0
        x1, y1, x2, y2 = (float(v) for v in args[:4])
        return int((x1 + x2) // 2), int((y1 + y2) // 2)

    # -- search --------------------------------------------------------
    def run(self, function, forced, keys=None):
        self.restore()
        self.forced, self.decisions, self.trace = forced, [], []
        self.forced_keys = keys or {}
        self.seen, self.steps = {}, 0
        self.clock, self.config_reads = 0.0, set()
        try:
            ok, value = self.runner(function)
            end = 'return' if ok else 'error'
            value = text(value)
        except PathLimit as exc:
            end, value = 'limit', str(exc)
        if end == 'error':
            # pcall hands back Python exceptions raised inside host callbacks.
            if isinstance(value, PathLimit) or 'PATH_BUDGET' in str(value):
                end = 'limit'
            value = str(value)
        return {'end': end, 'value': value, 'decisions': self.decisions,
                'trace': self.trace, 'config': sorted(self.config_reads)}

    def explore(self, name, max_hits=3, seeds=(), max_paths=500000):
        """DFS over outcomes with at most `max_hits` positive checks per path.

        A real frame satisfies only a handful of feature checks at once, so
        bounding simultaneous hits keeps every page reachable while avoiding
        the product of independent "don't care" checks.
        """
        function = self.globals[identifier(name)]
        if function is None:
            raise SystemExit(f'function not found: {name}')
        # Seeds are hit-sets observed on real frames. They reach pages that need
        # more simultaneous hits than max_hits (e.g. a dialog frame of four
        # checks plus one discriminator). Each seed is first minimised to the
        # checks that actually decide its page, then explored with one extra hit.
        stack = [([], max_hits, {})]
        for seed in seeds:
            keys = self.minimise(function, set(seed))
            if keys:
                stack.append(([], len(keys) + 1, {k: True for k in keys}))
        paths, done = [], set()
        while stack and len(paths) < max_paths:
            forced, budget, keys = stack.pop()
            result = self.run(function, forced, keys)
            outcomes = tuple(d['hit'] for d in result['decisions'])
            signature = (outcomes, tuple(sorted(keys)))
            if signature in done:
                continue
            done.add(signature)
            paths.append(result)
            if sum(outcomes) >= budget:
                continue
            for j in range(len(outcomes) - 1, len(forced) - 1, -1):
                if not outcomes[j]:
                    stack.append((list(outcomes[:j]) + [True], budget, keys))
        return paths, bool(stack)

    def minimise(self, function, hits):
        """Drop hits that do not change the returned page."""
        target = self.run(function, [], {k: True for k in hits})['value']
        if target is None:
            return set()
        for key in sorted(hits):
            trial = hits - {key}
            if self.run(function, [], {k: True for k in trial})['value'] == target:
                hits = trial
        return hits


def main():
    name, output = sys.argv[1], Path(sys.argv[2])
    hits = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    seeds = json.loads(Path(sys.argv[4]).read_text(encoding='utf-8')) if len(sys.argv) > 4 else []
    started = time.time()
    paths, truncated = Explorer().explore(name, hits, seeds)
    # Traces are only needed for the paths' side effects; keep them compact.
    for p in paths:
        p['trace'] = [t for t in p['trace'] if t[0] != 'check']
    output.write_text(json.dumps({'function': name, 'dpi': 180, 'max_hits': hits, 'seeds': len(seeds),
                                  'truncated': truncated, 'paths': paths}, ensure_ascii=False), encoding='utf-8')
    ends = {}
    for p in paths:
        ends[p['end']] = ends.get(p['end'], 0) + 1
    print(f'{name}: {len(paths)} paths in {time.time()-started:.1f}s, truncated={truncated}, ends={ends}')


if __name__ == '__main__':
    main()
