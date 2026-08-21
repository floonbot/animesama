import os
import sys

_meipass = getattr(sys, "_MEIPASS", None)
if _meipass:
    _browsers = os.path.join(_meipass, "ms-playwright")
    if os.path.isdir(_browsers):
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", _browsers)
