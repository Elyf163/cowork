#!/usr/bin/env python3
"""Backward-compatible entry point for Reasonix Cowork rounds."""

from pathlib import Path
import os
import sys


runner = Path(__file__).with_name("run_executor.py")
os.execv(sys.executable, [sys.executable, str(runner), *sys.argv[1:], "--executor", "reasonix"])
