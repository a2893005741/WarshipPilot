"""Extract what each original task function does on each page (dev tool).

For a task function (收远征, 出征战斗, ...) and every page rule, the page's
checks are forced to hit (static frame) and the task is run until it has
emitted a few inputs or stopped. The first inputs are that task's action on
that page: tab switches, "collect" buttons, back-to-home and so on. These
feed the native navigation graph and task handlers.

    uv run python tools/legacy_extract/build_policies.py 收远征 打战役 打演习 出征战斗
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from explore import Explorer, PathLimit, identifier  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


class Policy(Explorer):
    MAX_INPUTS = 3

    def sdk(self, command, *args):
        result = super().sdk(command, *args)
        if sum(1 for t in self.trace if t[0] in ('tap', 'touch')) >= self.MAX_INPUTS * (1 + 2 * (command == 219)):
            raise PathLimit('enough inputs')
        return result


def keys_for(pages, rule, extra=()):
    keys = {}
    for group in rule['all']:
        check = pages['checks'][group[0]]
        keys[json.dumps([check['kind'], check['args']], ensure_ascii=False)] = True
    for k in extra:
        keys[k] = True
    return keys


def main():
    pages = json.loads((ROOT / 'assets/pages.json').read_text(encoding='utf-8'))
    explorer = Policy()
    out = {}
    for task in sys.argv[1:]:
        function = explorer.globals[identifier(task)]
        if function is None:
            print('missing function', task)
            continue
        table = {}
        for rule in pages['pages']:
            if rule['name'] in table:
                continue
            result = explorer.run(function, [], keys_for(pages, rule))
            inputs = [{t[0]: t[1]} for t in result['trace'] if t[0] in ('tap', 'touch', 'unsupported')]
            logs = [t[1] for t in result['trace'] if t[0] == 'log'][:3]
            queried = [d for d in result['decisions'] if not d['hit']]
            table[rule['name']] = {'end': result['end'], 'value': str(result['value'])[:80],
                                   'inputs': inputs, 'logs': logs,
                                   'extra_checks': len(queried)}
        out[task] = table
        moving = sum(1 for v in table.values() if v['inputs'])
        print(f'{task}: {moving}/{len(table)} pages produce input')
    (ROOT / 'tools/legacy_extract/policies.json').write_text(json.dumps(out, ensure_ascii=False, indent=1),
                                                            encoding='utf-8')


if __name__ == '__main__':
    main()
