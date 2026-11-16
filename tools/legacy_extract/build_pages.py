"""Turn an exploration of 现在画面 into ALAS-style page rules (dev tool).

Each page becomes AND-of-groups, where a group is OR-of-alternative checks
(e.g. "back button, one of three skins"). Page order is derived, not guessed:
whenever a path's hit-set satisfies the rules of several pages, the page the
original function returned must be tried first. The result is replayed
against every explored path and the disagreements are reported.

    uv run python tools/legacy_extract/build_pages.py explore.json assets/pages.json
"""
from collections import defaultdict
from graphlib import TopologicalSorter, CycleError
import hashlib
import itertools
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]


def check_key(decision):
    return json.dumps([decision['kind'], decision['args']], ensure_ascii=False)


def factor(rules):
    """rules: set of frozensets. Return list of groups if rules == product(groups)."""
    items = sorted(set().union(*rules))
    parent = {i: i for i in items}

    def find(i):
        while parent[i] != i:
            i = parent[i]
        return i

    def alternative(a, b):
        return all((r - {a}) | {b} in rules for r in rules if a in r and b not in r)

    for a, b in itertools.combinations(items, 2):
        if alternative(a, b) and alternative(b, a):
            parent[find(a)] = find(b)
    groups = defaultdict(list)
    for i in items:
        groups[find(i)].append(i)
    groups = sorted(groups.values(), key=lambda g: g[0])
    product = {frozenset(c) for c in itertools.product(*groups)}
    return groups if product == rules else None


def main():
    source, output = Path(sys.argv[1]), Path(sys.argv[2])
    data = json.loads(source.read_text(encoding='utf-8'))
    paths = [p for p in data['paths'] if p['end'] == 'return']
    checks = {}
    order = {}
    for d in paths[0]['decisions']:  # all-miss path: canonical evaluation order
        order.setdefault(check_key(d), len(order))
    by_page = defaultdict(set)
    hitsets = []
    for p in paths:
        for d in p['decisions']:
            checks.setdefault(check_key(d), {'kind': d['kind'], 'args': d['args']})
        hits = frozenset(check_key(d) for d in p['decisions'] if d['hit'])
        hitsets.append((hits, p['value']))
        if p['value']:
            by_page[p['value']].add(hits)

    # Minimal hit-sets per page, then factor into AND-of-OR groups.
    units = []  # (page, [groups]) — a page may need several units if it doesn't factor
    for page, sets in by_page.items():
        minimal = {s for s in sets if not any(o < s for o in sets)}
        groups = factor(minimal)
        if groups:
            units.append((page, groups))
        else:
            units.extend((page, [[c] for c in sorted(s)]) for s in minimal)

    forbid = defaultdict(set)  # unit index -> checks that must NOT match

    def satisfied(unit, hits, index=None):
        if index is not None and forbid[index] & hits:
            return False
        return all(any(c in hits for c in group) for group in unit[1])

    # Precedence: the returned page's unit must precede any other satisfied unit.
    graph = defaultdict(set)
    for index, unit in enumerate(units):
        graph[index]
    for hits, value in hitsets:
        winners = [i for i, u in enumerate(units) if u[0] == value and satisfied(u, hits)]
        losers = [i for i, u in enumerate(units) if u[0] != value and satisfied(u, hits)]
        for w in winners[:1]:
            for loser in losers:
                graph[loser].add(w)
    # Earliest position each check is queried on any path approximates its
    # place in the original if-chain. Units without an explicit precedence
    # constraint (their checks never co-occur on a path because the earlier
    # branch returns first) are ordered by the point where they can decide.
    earliest = {}
    for p in paths:
        for position, d in enumerate(p['decisions']):
            k = check_key(d)
            earliest[k] = min(earliest.get(k, position), position)

    def rank(i):
        return (max(min(earliest.get(c, 10**6) for c in g) for g in units[i][1]),
                min(order.get(c, 10**6) for g in units[i][1] for c in g))
    try:
        sorter = TopologicalSorter(graph)
        sorter.prepare()
        sequence = []
        while sorter.is_active():
            ready = sorted(sorter.get_ready(), key=rank)
            sequence.extend(ready)
            sorter.done(*ready)
        cycle = None
    except CycleError as exc:
        cycle = exc.args[1]
        sequence = sorted(range(len(units)), key=rank)

    # Replay every explored hit-set through the ordered rules. Where a unit
    # fires but the original returned something else, look for a check that
    # is present in every such false positive and absent whenever the unit
    # correctly wins: that is a negated condition ("if X == 0") in the source.
    def replay():
        wrong, right = defaultdict(list), defaultdict(list)
        mismatches = defaultdict(int)
        for hits, value in hitsets:
            index = next((i for i in sequence if satisfied(units[i], hits, i)), None)
            found = units[index][0] if index is not None else None
            if found != value:
                mismatches[f'{value} -> {found}'] += 1
                if index is not None:
                    wrong[index].append(hits)
            elif index is not None:
                right[index].append(hits)
        return mismatches, wrong, right

    for _ in range(5):
        mismatches, wrong, right = replay()
        if not wrong:
            break
        for index, false_hits in wrong.items():
            own = set().union(*units[index][1])
            common = frozenset.intersection(*false_hits) - own
            seen_right = set().union(*right[index]) if right[index] else set()
            candidates = sorted(common - seen_right, key=lambda c: order.get(c, 10**6))
            if candidates:
                forbid[index].add(candidates[0])
    mismatches, _, _ = replay()
    ordered = [(units[i], forbid[i]) for i in sequence]

    ids = {key: f'c{n:03}' for n, key in enumerate(sorted(checks, key=lambda k: order.get(k, 10**6)))}
    result = {
        'source': {'function': data['function'], 'dpi': data['dpi'], 'max_hits': data.get('max_hits'),
                   'paths': len(paths), 'bytecode_sha256': hashlib.sha256(
                       (ROOT / 'assets/legacy/main.lua52.luac').read_bytes()).hexdigest()},
        'checks': {ids[k]: v for k, v in sorted(checks.items(), key=lambda kv: ids[kv[0]])},
        'pages': [{'name': page, 'all': [[ids[c] for c in group] for group in groups],
                   **({'none': sorted(ids[c] for c in banned)} if banned else {})}
                  for (page, groups), banned in ordered],
        'replay': {'mismatches': dict(mismatches), 'cycle': cycle},
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding='utf-8')
    total = sum(mismatches.values())
    print(f'{len(by_page)} pages, {len(ordered)} rules, {len(checks)} checks; '
          f'replay {len(hitsets) - total}/{len(hitsets)} agree; cycle={bool(cycle)}')
    for k, v in sorted(mismatches.items(), key=lambda kv: -kv[1])[:20]:
        print(f'  {v:6}  {k}')
    return total == 0 and not cycle


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
