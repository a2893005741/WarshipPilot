"""Generate menu/args from ALAS-style task, argument, default and override YAML."""
import json
from pathlib import Path
import yaml

FOLDER = Path(__file__).parent / 'argument'


def build():
    load = lambda name: yaml.safe_load((FOLDER / name).read_text(encoding='utf-8')) or {}
    task, args, labels = load('task.yaml'), load('argument.yaml'), load('gui.yaml')
    for name in ('default.yaml', 'override.yaml'):
        for path, values in load(name).items():
            owner, group, argument = path.split('.', 2)
            args[owner][group][argument].update(values)
    for menu in task['menu'].values():
        for owner, groups in menu['tasks'].items():
            if set(groups) != set(args[owner]):
                raise ValueError(f'菜单和字段分组不一致：{owner}')
    schema = {'menu': task['menu'], 'tasks': task['tasks'], 'groups': labels, 'args': args}
    for name, value in [('args.json', args), ('menu.json', task['menu']), ('schema.json', schema)]:
        (FOLDER / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    template = {'schema_version': 2,
                'Device': {'serial': '', 'interval': 3, 'screenshot_method': 'nemu_ipc',
                           'control_method': 'ADB', 'mumu_path': ''},
                'Tasks': {task: {group: {name: field['value'] for name, field in fields.items()}
                                 for group, fields in groups.items()} for task, groups in args.items()},
                'Scheduler': {'Enable': False, 'NextRun': {}}}
    (FOLDER.parents[2] / 'config/template.json').write_text(json.dumps(template, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return schema


if __name__ == '__main__':
    schema = build()
    print(f"Generated {len(schema['tasks'])} tasks")
