"""Compatibility entry point for the grouped RSS history browser checks."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).with_name("browser_rss_grouped_history.py")))
