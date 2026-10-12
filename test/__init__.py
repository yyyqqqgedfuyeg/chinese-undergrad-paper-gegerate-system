"""历史 test.* 导入兼容层；测试按问题迁移至 tests/。"""
from pathlib import Path
__path__ = [str(p) for p in (Path(__file__).resolve().parents[1]/"tests").iterdir() if p.is_dir()]
