"""Schema and task/group/argument operations used by HTTP and WebSocket."""
from module.config.config import Config
from module.config.schema import schema, config_values, save_field


class ConfigService:
    def __init__(self, runtime):
        self.runtime = runtime

    def schema(self):
        return schema()

    def get(self, task):
        return config_values(self.runtime.store.root, task)

    def set(self, path, value):
        runtime = self.runtime
        with runtime.lock:
            result = save_field(runtime.store.root, path, value)
            if path.endswith('.Scheduler.NextRun'):
                runtime.automation.due = Config(runtime.store.root).section('Scheduler').get('NextRun', {})
        runtime.wake.set()
        return result
