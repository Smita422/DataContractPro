"""Entry point for executing schemaguard via python -m schemaguard."""

import sys
from schemaguard.cli import main

if __name__ == "__main__":
    sys.exit(main())
