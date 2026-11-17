"""Method registry of the AzurPilot WebUI protocol, served by WarshipPilot."""
from dataclasses import dataclass
import secrets
from typing import Callable

from module.api.alas import protocol as p
from module.api.alas.config_adapter import copy_schema, search
from module.api.alas.service import INSTANCE, WarshipService, launcher_status


@dataclass(frozen=True)
class Method:
    params: type
    handler: Callable
    mutates: bool = False
    local_only: bool = False
    data_channel: bool = False


def single_instance(_):
    raise p.ApiError('UNSUPPORTED', '舰R助手只管理一个游戏实例，不能新建或删除实例')


class Router:
    def __init__(self, runtime, key=''):
        self.runtime = runtime
        self.key = key
        self.service = service = WarshipService(runtime)
        self.instance = INSTANCE
        self.token = secrets.token_urlsafe(32)
        self.methods = {
            'system.ping': Method(p.Params, lambda _: {'pong': True}),
            'schema.get': Method(p.SchemaParams, lambda _: copy_schema(), data_channel=True),
            'search.content': Method(p.SearchContentParams, lambda x: search(x.query)),
            'instances.list': Method(p.Params, lambda _: service.instances()),
            'instances.create': Method(p.CreateParams, single_instance, True),
            'instances.importable': Method(p.Params, lambda _: []),
            'instances.importConfig': Method(p.ImportParams, single_instance, True),
            'instances.delete': Method(p.RevisionParams, single_instance, True),
            'config.get': Method(p.InstanceParams, lambda x: self.config(x).get(), data_channel=True),
            'config.export': Method(p.InstanceParams, lambda x: self.config(x).export(), data_channel=True),
            'config.patch': Method(p.PatchParams, lambda x: self.config(x).patch(x.revision, x.changes), True),
            'overview.get': Method(p.InstanceParams, lambda x: service.overview(x.instance)),
            'scheduler.start': Method(p.InstanceParams, lambda x: service.scheduler(x.instance, True), True),
            'scheduler.stop': Method(p.InstanceParams, lambda x: service.scheduler(x.instance, False), True),
            'tasks.run': Method(p.TaskParams, lambda x: service.run_task(x.instance, x.task), True),
            'tasks.runNow': Method(p.TaskParams, lambda x: service.run_now(x.instance, x.task), True),
            'logs.get': Method(p.LogsParams, lambda x: service.logs(x.instance, x.after), data_channel=True),
            'preview.capture': Method(p.InstanceParams, lambda x: service.capture(x.instance), data_channel=True),
            'errors.list': Method(p.ErrorsListParams, lambda x: service.errors(x.instance, x.offset, x.limit), data_channel=True),
            'errors.detail': Method(p.ErrorRecordParams, lambda x: service.error_detail(x.instance, x.record), data_channel=True),
            'errors.file': Method(p.ErrorFileParams, lambda x: service.error_file(x.instance, x.record, x.name), data_channel=True),
            'settings.get': Method(p.Params, lambda _: service.settings()),
            'settings.patch': Method(p.DeployParams, lambda x: service.save_settings(x.values), True),
            'startup.get': Method(p.InstanceParams, lambda _: {'enabled': False, 'remember': False}),
            'startup.set': Method(p.StartupParams, lambda _: {'enabled': False, 'remember': False}, True),
            'updater.status': Method(p.Params, lambda _: service.update_status()),
            'updater.commits': Method(p.CommitsParams, lambda x: service.commits(x.offset, x.limit)),
            'updater.fetch': Method(p.Params, lambda _: service.update_action('fetch'), True),
            'updater.apply': Method(p.Params, lambda _: service.update_action('apply'), True),
            'updater.cancel': Method(p.Params, lambda _: service.update_action('cancel'), True),
            # WarshipPilot device/tool pages keep the earlier HTTP API: an
            # authenticated session (password = this access code, or local)
            # receives the same Bearer key.
            'warship.httpKey': Method(p.Params, lambda _: {'key': self.key}),
            # Shell features of AzurPilot that WarshipPilot does not have.
            'launcher.status': Method(p.Params, lambda _: launcher_status(), local_only=True),
            'launcher.autostart.set': Method(p.LauncherAutostartParams, lambda _: {'commandId': 'none', 'status': 'pending'}, True, True),
            'launcher.command.get': Method(p.LauncherCommandParams, lambda x: {'id': x.commandId, 'status': 'expired', 'deadline': 0}, local_only=True),
            'announcement.get': Method(p.AnnouncementParams, lambda _: None),
            'background.access': Method(p.Params, lambda _: {'token': self.token}),
            'background.gallery.list': Method(p.Params, lambda _: []),
            'background.resolve': Method(p.LooseParams, lambda _: single_feature('自定义背景')),
            'background.gallery.add': Method(p.LooseParams, lambda _: single_feature('自定义背景'), True),
            'background.gallery.remove': Method(p.LooseParams, lambda _: {'removed': False}, True),
            'background.gallery.open': Method(p.Params, lambda _: single_feature('自定义背景'), True),
            'plugins.access': Method(p.Params, lambda _: {'token': self.token}),
            'plugins.list': Method(p.Params, lambda _: []),
        }

    def config(self, params):
        self.service.check(params.instance)
        return self.service.config

    def dispatch(self, name, raw, local=False):
        method = self.methods.get(name)
        if method is None:
            raise p.ApiError('NOT_FOUND', f'舰R助手不提供此功能：{name}')
        if method.local_only and not local:
            raise p.ApiError('LOCAL_ONLY', '只允许本机调用')
        return method.handler(method.params.model_validate(raw))


def single_feature(name):
    raise p.ApiError('UNSUPPORTED', f'舰R助手暂不支持{name}')
