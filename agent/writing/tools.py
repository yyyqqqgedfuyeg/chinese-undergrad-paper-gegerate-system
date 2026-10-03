"""绑定单次任务工作目录的工具；不改进程 cwd 或全局 WORKSPACE_DIR。"""

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile

from langchain_core.tools import tool

from ..agent import Skill


def workspace_path(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"路径不在本次工作目录内: {value}")
    return path


def load_project_skills() -> list[Skill]:
    directory = Path(__file__).resolve().parents[2] / "skills"
    return [Skill(name=path.parent.name, description=f"项目技能 {path.parent.name}",
                  instructions=f"技能目录（相对脚本路径基于此目录）: {path.parent}\n"
                  + path.read_text(encoding="utf-8"))
            for path in sorted(directory.glob("*/SKILL.md"))]


def create_writing_tools(workspace_dir: str):
    root = Path(workspace_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)

    @tool
    def bash(command: str, timeout_seconds: int = 60) -> str:
        """在本次工作目录执行 bash，生成/运行绘图代码、HTML 页面、截图及图片导出。返回真实退出码；失败不自动重放命令。"""
        if not 1 <= timeout_seconds <= 180:
            raise ValueError("timeout_seconds 必须为 1-180")
        env = dict(os.environ)
        env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env.get("PATH", "")
        # 临时文件防止大量工具输出占满进程内存。bash 是执行能力，不是文件系统沙箱。
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            proc = subprocess.Popen(command, shell=True, executable=shutil.which("bash"),
                                    cwd=root, env=env, stdout=stdout, stderr=stderr,
                                    start_new_session=True)
            timed_out = False
            try:
                proc.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            stdout.seek(0)
            stderr.seek(0)
            return json.dumps({"exit_code": proc.returncode, "timed_out": timed_out,
                               "stdout": stdout.read(12000).decode("utf-8", errors="replace"),
                               "stderr": stderr.read(6000).decode("utf-8", errors="replace")}, ensure_ascii=False)

    @tool
    def read(file_path: str, start_line: int = 1, max_lines: int = 200) -> str:
        """读取本次工作目录内的文本，支持分页读取前文正文和已生成代码。"""
        if start_line < 1 or not 1 <= max_lines <= 1000:
            raise ValueError("无效的行范围")
        lines = workspace_path(root, file_path).read_text(encoding="utf-8").splitlines()
        return "\n".join(lines[start_line - 1:start_line - 1 + max_lines])

    @tool
    def write(file_path: str, content: str) -> str:
        """在本次工作目录创建或覆盖 UTF-8 文件，例如 Python/JS 绘图代码和 HTML 页面。"""
        path = workspace_path(root, file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path.relative_to(root))

    @tool
    def edit(file_path: str, target_content: str, replacement_content: str) -> str:
        """精确替换文件中唯一匹配的一处文本；修改前可用 read 查看原文。"""
        path = workspace_path(root, file_path)
        content = path.read_text(encoding="utf-8")
        if not target_content or content.count(target_content) != 1:
            raise ValueError("target_content 必须非空且唯一匹配")
        path.write_text(content.replace(target_content, replacement_content, 1), encoding="utf-8")
        return str(path.relative_to(root))

    return [bash, read, write, edit]
