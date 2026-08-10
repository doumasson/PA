#!/usr/bin/env python3
"""Entry point for the repair daemon (run by albus-repair.timer).

Usage: /home/admin/pa/.venv/bin/python tools/repair_daemon.py
Working directory must be the live tree (~/pa-v2) so `pa` imports resolve.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pa.plugins.repair.daemon import main

if __name__ == "__main__":
    asyncio.run(main())
