"""Extract the default action the original takes on each page (dev tool).

With the global 有用 = 0, the original 现在画面 does not only name the page
but also handles it (taps "continue", closes a popup, ...). Task functions
fall back to this for pages they do not handle themselves. For every rule in
assets/pages.json the rule's checks are forced to hit and the emitted
inputs are recorded, giving ALAS-style generic page handlers.

    uv run python dev_tools/legacy_extract/build_handlers.py
"""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from explore import Explorer, identifier  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def main():
    pages = json.loads((ROOT / 'assets/pages.json').read_text(encoding='utf-8'))
    explorer = Explorer(useful=0)
    function = explorer.globals[identifier('现在画面')]
    handlers = {}
    for rule in pages['pages']:
        keys = {}
        for group in rule['all']:
            check = pages['checks'][group[0]]
            keys[json.dumps([check['kind'], check['args']], ensure_ascii=False)] = True
        result = explorer.run(function, [], keys)
        actions = []
        for kind, value in result['trace']:
            if kind == 'tap':
                actions.append({'tap': [round(v, 1) for v in value]})
            elif kind == 'touch':
                actions.append({'touch': value})
            elif kind == 'wait':
                if actions and 'wait' in actions[-1]:
                    actions[-1]['wait'] += value
                else:
                    actions.append({'wait': value})
            elif kind == 'unsupported':
                actions.append({'unsupported': value})
        # A static frame makes "tap then wait for the page to change" loop;
        # keep only the first repetition of the action pattern.
        taps = [a for a in actions if 'tap' in a or 'touch' in a]
        entry = {'returned': result['value'], 'end': result['end'], 'actions': actions[:12]}
        if taps:
            entry['first_tap'] = taps[0].get('tap')
        handlers.setdefault(rule['name'], entry)
    out = ROOT / 'assets/page_handlers.json'
    out.write_text(json.dumps(handlers, ensure_ascii=False, indent=1), encoding='utf-8')
    acting = sum(1 for h in handlers.values() if h.get('first_tap'))
    print(f'{len(handlers)} pages, {acting} with a default tap')


if __name__ == '__main__':
    main()
