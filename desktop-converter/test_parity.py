"""Keep desktop encoding and preservation checks aligned with FjordSeed."""
import ast
from pathlib import Path

import pytest


@pytest.mark.parametrize('name', ['command', 'probe', 'validate', 'restore_flags'])
def test_desktop_matches_server(name):
    here = Path(__file__).parent
    def function(path):
        tree = ast.parse(path.read_text(encoding='utf-8'))
        return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    assert ast.dump(function(here / 'encode_core.py')) == ast.dump(function(here.parent / 'converter_worker.py'))
