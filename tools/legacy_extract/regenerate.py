"""Regenerate assets/pages.json from the recovered bytecode.

    uv run python tools/legacy_extract/regenerate.py [screenshots-glob ...]

1. explore 现在画面 (all paths with <=4 simultaneous hits, plus seeds.json);
2. build ordered AND/OR/NOT page rules and replay them against every path;
3. if screenshot globs are given, compare rules with the original function on
   those frames and fold their hit-sets into seeds.json.

Run step 3 then regenerate again whenever new real frames show a page the
rules miss.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def run(*args):
    print('>', ' '.join(str(a) for a in args[1:]), flush=True)
    return subprocess.run([sys.executable, *map(str, args)], cwd=ROOT).returncode


def main():
    with tempfile.TemporaryDirectory() as tmp:
        exploration = Path(tmp) / 'exploration.json'
        if run(HERE / 'explore.py', '现在画面', exploration, 4, HERE / 'seeds.json'):
            return 1
        if run(HERE / 'build_pages.py', exploration, ROOT / 'assets' / 'pages.json'):
            return 1
    if len(sys.argv) > 1:
        return run(HERE / 'validate_pages.py', ROOT / 'assets' / 'pages.json', *sys.argv[1:])
    return 0


if __name__ == '__main__':
    sys.exit(main())
