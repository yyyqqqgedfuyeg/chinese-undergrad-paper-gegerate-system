"""将现有 skill 脚本绑定到明确输入与独立输出目录。"""
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from langchain_core.tools import tool
from ..paths import project_root
from ..security.policy import bind_role_tools


def create_template_tools(source_path, workspace_dir):
    root = Path(workspace_dir).resolve()
    output = root / "template"
    if output.resolve() != output:
        raise PermissionError("模板输出目录不能为符号链接")
    source = Path(source_path).resolve(strict=True) if source_path else None
    if source and not source.is_file():
        raise ValueError("模板输入必须为文件")
    original_hash = sha256(source.read_bytes()).hexdigest() if source else None
    if source and source.is_relative_to(output):
        raise ValueError("输入模板不能位于输出目录")
    script = project_root() / "skills/docx/scripts/template_pipeline.py"

    def execute(action, plan=None):
        if source is None:
            raise ValueError("请先由调用方绑定 source_path；模型不能自行选择宿主文件")
        if sha256(source.read_bytes()).hexdigest() != original_hash:
            raise ValueError("输入模板发生变化")
        output.mkdir(parents=True, exist_ok=True)
        args = [sys.executable, str(script), action, "--source", str(source), "--out", str(output)]
        if plan is not None:
            plan = {**plan, "source_sha256": original_hash}
            path = output / "cleaning-plan.json"
            path.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
            args += ["--plan", str(path)]
        elif action == "verify":
            args += ["--plan", str(output / "cleaning-plan.json")]
        result = subprocess.run(args, capture_output=True, text=True, timeout=180,
                                env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
        if result.returncode:
            raise ValueError(result.stderr[-4000:] or result.stdout[-4000:])
        if sha256(source.read_bytes()).hexdigest() != original_hash:
            raise ValueError("脚本改动了原始模板")
        return result.stdout[-10000:]

    @tool
    def inspect_template() -> dict:
        """读取已绑定模板的段落、样式和结构，不接受任意路径。"""
        execute("inspect")
        return json.loads((output / "summary.json").read_text())

    @tool
    def build_template(plan: dict) -> str:
        """按有依据的清洗计划生成模板副本；原始学校模板只读。"""
        return execute("build", plan)

    @tool
    def verify_template() -> str:
        """校验复刻、模板清洗和样式结果。"""
        return execute("verify")

    return list(bind_role_tools("template", [inspect_template, build_template, verify_template]).values())
