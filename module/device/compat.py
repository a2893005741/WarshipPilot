"""Stand-ins for the AzurPilot modules the ported device methods import.

AzurPilot's logger, exceptions, runtime constants and package table are
replaced by small local equivalents so module.device carries no Azur Lane
configuration. Values mirror AzurPilot module/base/runtime_params.py and
module/config/config_manual.py at the ported revision (see docs/ALAS-PORT.json).
"""
import logging

_log = logging.getLogger('warship.device')


class _Logger:
    """AzurPilot logger surface: info/warning/... plus attr() and hr()."""

    def __getattr__(self, name):
        return getattr(_log, name)

    @staticmethod
    def attr(name, text):
        _log.info('[%s] %s', name, text)

    @staticmethod
    def hr(title, level=3):
        _log.info('==== %s ====', title)


logger = _Logger()


class RequestHumanTakeover(Exception):
    """The device/method cannot continue without the user."""


class EmulatorNotRunningError(Exception):
    pass


class ScriptError(Exception):
    pass


# module/base/runtime_params.py
RETRY_TRIES = 5
RETRY_DELAY = 3
IMAGE_TRUNCATED_THRESHOLD = 3

# module/config/server.py (only the game this project drives)
DICT_PACKAGE_TO_ACTIVITY = {'com.huanmeng.zhanjian2': 'com.unity3d.player.UnityPlayerActivity'}


def deep_get(d, keys, default=None):
    """module/config/deep.py deep_get."""
    if type(keys) is str:
        keys = keys.split('.')
    try:
        for k in keys:
            d = d[k]
        return d
    except (KeyError, IndexError, TypeError):
        return default
