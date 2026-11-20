#!/usr/bin/env python3
"""Start Fullframe: python run.py"""
import sys

if sys.version_info < (3, 9):
    sys.exit("Fullframe needs Python 3.9 or newer (you have %s)." % sys.version.split()[0])

try:
    sys.stdout.reconfigure(errors="replace")
    sys.stderr.reconfigure(errors="replace")
except AttributeError:
    pass

from fullframe.server import main  # noqa: E402

if __name__ == "__main__":
    main()
