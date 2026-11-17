"""Isolated WebUI for browser tests: real APIs, temporary data, no device I/O."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import uvicorn

from module.api.app import create_app
from module.config.task_settings import TaskDraft, save_task
from module.runtime.runtime import Runtime


def idle(runtime):
    runtime.stop_event.wait()


if __name__ == '__main__':
    resources = Path(__file__).resolve().parents[1]
    with TemporaryDirectory(prefix='warship-mobile-') as folder, patch.object(Runtime, '_loop', idle):
        root = Path(folder)
        save_task(root, 'expedition', TaskDraft(enabled=True))
        save_task(root, 'reward', TaskDraft(enabled=True))
        runtime = Runtime(root, resources)
        runtime.store.event('手机端界面验证：使用独立配置，不连接模拟器。')
        app = create_app(runtime, 'mobile-e2e', lambda: None)
        uvicorn.run(app, host='127.0.0.1', port=22393, access_log=False)
