"""Package corresponding source without runtime data, credentials or evidence."""
import argparse
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser()
parser.add_argument('--output', default='dist')
options = parser.parse_args()
version = (root/'backend'/'version.py').read_text(encoding='utf-8').split('"')[-2]
output = root/options.output/f'WarshipPilot-{version}-source.zip'
output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name in ['backend', 'scripts', 'docs', 'assets', 'bin', 'tools', 'tests', 'frontend/src']:
        for path in (root/name).rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':
                archive.write(path, path.relative_to(root))
    for name in ['main.py', 'pyproject.toml', 'uv.lock', 'LICENSE', 'README.md',
                 'frontend/package.json', 'frontend/package-lock.json', 'frontend/tsconfig.json',
                 'frontend/vite.config.ts', 'frontend/index.html']:
        path = root/name
        if path.is_file():
            archive.write(path, path.relative_to(root))
print(output)
