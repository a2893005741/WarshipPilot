"""Shared device failure types, matching the ALAS module boundary."""


class RequestHumanTakeover(Exception):
    """The device cannot continue without user action."""


class EmulatorNotRunningError(Exception):
    pass


class ScriptError(Exception):
    pass
