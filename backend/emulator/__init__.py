"""Device methods ported from AzurPilot.

As in AzurPilot module/device/__init__.py: install the lightweight
pkg_resources shim before adbutils / uiautomator2 are imported (Python 3.14
environments do not ship setuptools' pkg_resources).
"""
from backend.emulator.pkg_resources import get_distribution  # noqa: F401
