"""Minimal requests-based replacement for AzurPilot module/base/http.py.

Only what method/utils.py uses to fetch the atx-agent archive for
uiautomator2: download_file(), get(..., stream=True) and RequestException.
"""
from contextlib import contextmanager
import os
import tempfile

import requests
from requests import RequestException  # noqa: F401  (re-exported)


def download_file(url, storepath, timeout=30):
    os.makedirs(os.path.dirname(storepath) or '.', exist_ok=True)
    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(storepath) or '.')
        with os.fdopen(fd, 'wb') as f:
            for chunk in response.iter_content(65536):
                f.write(chunk)
    os.replace(tmp, storepath)
    return storepath


@contextmanager
def get(url, download=False, stream=False, headers=None, timeout=30, **kwargs):
    response = requests.get(url, stream=stream, headers=headers, timeout=timeout)
    try:
        response.raise_for_status()
        yield response
    finally:
        response.close()
