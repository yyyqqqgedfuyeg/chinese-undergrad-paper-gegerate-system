"""Compatibility entry point for the production local LibreOffice renderer."""
from pathlib import Path
import runpy

if __name__ == '__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[2] / 'src/agent/assembly/layout_uno.py'), run_name='__main__')
