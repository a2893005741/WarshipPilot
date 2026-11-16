"""Stand-ins for the AzurPilot modules the ported device methods import.

AzurPilot's logger, exceptions, runtime constants and package table are
replaced by small local equivalents so module.device carries no Azur Lane
configuration. Values mirror AzurPilot module/base/runtime_params.py and
module/config/config_manual.py at the ported revision (see docs/ALAS-PORT.json).
"""
from module.logger import logger
from module.exception import RequestHumanTakeover, EmulatorNotRunningError, ScriptError


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
