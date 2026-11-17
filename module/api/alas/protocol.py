"""Request envelope, errors and parameter models of the AzurPilot WebUI protocol.

Shapes follow H:\\ALAS\\AzurPilot module/api/protocol.py so the reused frontend's
generated client validates unchanged. Only methods WarshipPilot serves are
modelled; Azur Lane-only families (dock, mind, stock, opsi, ...) are absent.
"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

VERSION = 1


class ApiError(Exception):
    """A failure that is safe to show to the user."""

    def __init__(self, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.code, self.message, self.details = code, message, details


class Params(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class LooseParams(BaseModel):
    """Stubbed shell features accept their original parameters unchanged."""
    model_config = ConfigDict(extra='allow')


class Request(Params):
    v: Literal[1]
    type: Literal['request']
    id: StrictStr = Field(min_length=1, max_length=100)
    method: StrictStr = Field(min_length=1, max_length=80)
    params: dict[str, Any] = Field(default_factory=dict)


class AuthParams(Params):
    password: StrictStr = Field(default='', max_length=256)


class LauncherTicketParams(Params):
    ticket: StrictStr = Field(min_length=1, max_length=128)


class LauncherAutostartParams(Params):
    enabled: StrictBool


class LauncherCommandParams(Params):
    commandId: StrictStr = Field(min_length=1, max_length=100)


class SchemaParams(Params):
    language: Literal['zh-CN', 'en-US', 'ja-JP', 'zh-TW'] = 'zh-CN'


class SearchContentParams(Params):
    query: StrictStr = Field(min_length=1, max_length=64)


class AnnouncementParams(Params):
    force: StrictBool = False


class InstanceParams(Params):
    instance: StrictStr = Field(min_length=1, max_length=64)


class RevisionParams(InstanceParams):
    revision: StrictStr


class CreateParams(LooseParams):
    name: StrictStr = Field(min_length=1, max_length=64)


class ImportParams(Params):
    name: StrictStr = Field(min_length=1, max_length=64)
    content: StrictStr = Field(min_length=2, max_length=2_000_000)


class ConfigChange(Params):
    path: StrictStr = Field(min_length=1, max_length=180)
    value: Any


class PatchParams(InstanceParams):
    revision: StrictStr | None = Field(default=None, min_length=1, max_length=64)
    changes: list[ConfigChange] = Field(min_length=1, max_length=200)


class TaskParams(InstanceParams):
    task: StrictStr = Field(min_length=1, max_length=80)


class LogsParams(InstanceParams):
    after: StrictInt = Field(default=0, ge=0)


class ErrorsListParams(InstanceParams):
    offset: StrictInt = Field(default=0, ge=0)
    limit: StrictInt = Field(default=30, ge=1, le=100)


class ErrorRecordParams(InstanceParams):
    """WarshipPilot fault folders are named by a 32-hex id (AzurPilot: ms stamp)."""
    record: StrictStr = Field(pattern=r'^[0-9a-f]{32}$')


class ErrorFileParams(ErrorRecordParams):
    name: StrictStr = Field(min_length=1, max_length=80)


class DeployParams(Params):
    values: dict[str, Any]


class StartupParams(InstanceParams):
    enabled: StrictBool | None = None
    remember: StrictBool | None = None


class CommitsParams(Params):
    offset: StrictInt = Field(default=0, ge=0)
    limit: StrictInt = Field(default=50, ge=1, le=100)


class SubscribeParams(Params):
    instance: StrictStr | None = None
    topics: list[Literal['instances', 'overview', 'logs', 'preview', 'stock', 'notifications', 'launcher',
                         'plugins']] = Field(max_length=8)


def response(request_id, result):
    return {'v': VERSION, 'type': 'response', 'id': request_id, 'ok': True, 'result': result}


def failure(request_id, error: ApiError):
    return {'v': VERSION, 'type': 'response', 'id': request_id, 'ok': False,
            'error': {'code': error.code, 'message': error.message, 'details': error.details}}
