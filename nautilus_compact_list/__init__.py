import os
import sys

try:
    # Look for version.py in parent directory
    _parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _parent_dir not in sys.path:
        sys.path.insert(0, _parent_dir)
    import version
    __version__ = version.__version__
except Exception:
    __version__ = "0.1.0"
