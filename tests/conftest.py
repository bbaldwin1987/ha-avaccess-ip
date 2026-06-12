"""Test bootstrap.

`avaccess_ip/__init__.py` imports Home Assistant, which we don't need (and don't
install) for the hardware-independent unit tests covering `device` and
`transport`. We register a synthetic `avaccess_ip` package pointing at the
source directory *without* executing its `__init__.py`, so submodule imports
(`from avaccess_ip import device`) and their relative imports resolve normally.
"""

import os
import sys
import types

_ROOT = os.path.dirname(os.path.dirname(__file__))
_PKG_DIR = os.path.join(_ROOT, "custom_components", "avaccess_ip")

if "avaccess_ip" not in sys.modules:
    pkg = types.ModuleType("avaccess_ip")
    pkg.__path__ = [_PKG_DIR]  # make it a package without running __init__.py
    sys.modules["avaccess_ip"] = pkg
