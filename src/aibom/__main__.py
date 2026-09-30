"""Entry point for `python -m aibom`."""

from __future__ import annotations

import sys

from aibom.cli import main

if __name__ == "__main__":
    sys.exit(main())
