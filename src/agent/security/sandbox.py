"""Linux bubblewrap 执行器：仅挂载任务目录和只读运行时，禁网、隔离进程。

缺少隔离能力时直接失败，绝不退回宿主 shell。
"""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile


def scoped_path(root: Path, value: str) -> Path:
    root = root.resolve(strict=True)
    if value.startswith("/workspace/"):
        value = value.removeprefix("/workspace/")
    path = (root / value).resolve()
    if not path.is_relative_to(root) or path == root:
        raise PermissionError("只允许访问分配的工作区内文件")
    return path


class CodingSandbox:
    def __init__(self, workspace):
        self.root = Path(workspace).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.bwrap = shutil.which("bwrap")
        if not self.bwrap:
            raise RuntimeError("编码需要 bubblewrap，禁止回退到非隔离 Bash")

    def command(self, command):
        args = [self.bwrap, "--unshare-all", "--die-with-parent", "--new-session",
                "--cap-drop", "ALL"]
        runtime = ["/usr", "/bin", "/lib", "/lib64", sys.base_prefix, sys.prefix]
        # 只读依赖；不挂载项目、宿主 /tmp、/home、/proc 或环境凭据。
        mounted = []
        for value in runtime:
            path = Path(value)
            if path.exists() and not any(path == p or path.is_relative_to(p) for p in mounted):
                args += ["--ro-bind", str(path), str(path)]
                mounted.append(path)
        for value in ("/etc/fonts", "/etc/ld.so.cache"):
            if Path(value).exists():
                args += ["--ro-bind", value, value]
        args += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                 "--dir", "/home/sandbox", "--bind", str(self.root), "/workspace",
                 "--chdir", "/workspace", "--setenv", "HOME", "/home/sandbox",
                 "--setenv", "PATH", f"{sys.prefix}/bin:/usr/bin:/bin",
                 "--setenv", "LANG", "C.UTF-8", "--setenv", "PYTHONNOUSERSITE", "1",
                 "--setenv", "MPLCONFIGDIR", "/tmp/matplotlib",
                 "/bin/bash", "--noprofile", "--norc", "-c", command]
        return args

    def run(self, command: str, timeout_seconds: int = 60) -> str:
        if not isinstance(command, str) or not command.strip() or len(command) > 100000:
            raise ValueError("无效命令")
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 180:
            raise ValueError("timeout_seconds 必须为 1-180")
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            process = subprocess.Popen(self.command("set -o pipefail\n" + command), stdout=out, stderr=err,
                                       start_new_session=True, env={"PATH": "/usr/bin:/bin"})
            timed_out = False
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                process.kill()
                process.wait()
            finally:
                # 回收同一进程组；bwrap 的 PID namespace 同时回收后台后代。
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            out.seek(0); err.seek(0)
            return json.dumps({"exit_code": process.returncode, "timed_out": timed_out,
                               "stdout": out.read(16000).decode(errors="replace"),
                               "stderr": err.read(8000).decode(errors="replace")}, ensure_ascii=False)
