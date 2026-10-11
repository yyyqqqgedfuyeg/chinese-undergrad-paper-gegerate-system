"""源码检出兼容入口；实现位于 src/agent，安装后直接使用 src 包。"""
from pathlib import Path
__path__ = [str(Path(__file__).resolve().parents[1] / "src" / "agent")]
exec(compile((Path(__path__[0]) / "__init__.py").read_bytes(),
             str(Path(__path__[0]) / "__init__.py"), "exec"))
