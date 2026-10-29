"""Compatibility import for the shared desktop/server decoder selection."""
import sys
from pathlib import Path
if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from conversion_decoder import capabilities, select, subprocess
