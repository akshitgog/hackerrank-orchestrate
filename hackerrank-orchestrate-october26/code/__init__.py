"""Project package with the standard-library ``code`` API compatibility shim.

The project historically imports modules as ``code.src...``.  Python's
standard library also has a top-level ``code`` module, which pytest imports
through ``pdb``.  Re-exporting the standard-library symbols keeps both import
styles working instead of making the project package shadow ``InteractiveConsole``
and related debugger classes.
"""

from __future__ import annotations

import importlib.util
import sysconfig
from pathlib import Path

_stdlib_code = Path(sysconfig.get_path("stdlib")) / "code.py"
_spec = importlib.util.spec_from_file_location("_stdlib_code_module", _stdlib_code)
_module = None
if _spec is not None and _spec.loader is not None:
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    for _name in dir(_module):
        if not _name.startswith("__"):
            globals().setdefault(_name, getattr(_module, _name))

del importlib, sysconfig, Path, _stdlib_code, _spec, _module
