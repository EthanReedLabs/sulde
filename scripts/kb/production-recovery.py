#!/usr/bin/env python3
"""Exact, independent production recovery entrypoint."""
import sys
sys.dont_write_bytecode = True
from production_recovery_control import main

if __name__ == "__main__":
    raise SystemExit(main())
