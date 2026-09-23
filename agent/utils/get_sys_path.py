"""
utils/get_sys_path.py - 获取系统与工作区根路径工具

功能：
1. 自动定位当前项目工作区根路径（规范化绝对路径）。
2. 提供格式化提示词片段，用于直接注入 Agent 的 System Prompt。
"""

import os
from pathlib import Path


def get_workspace_path() -> str:
    """
    获取当前工作区根目录的绝对路径。
    优先读取环境变量 WORKSPACE_DIR；
    若未设置，则根据当前文件位置推断项目根目录 (agent/utils/get_sys_path.py 上推三级)。
    """
    env_workspace = os.getenv("WORKSPACE_DIR")
    if env_workspace and os.path.exists(env_workspace):
        return str(Path(env_workspace).resolve())

    # 当前文件位于 <root>/agent/utils/get_sys_path.py
    # parent: utils, parent.parent: agent, parent.parent.parent: <root>
    inferred_root = Path(__file__).resolve().parent.parent.parent
    return str(inferred_root)


def get_workspace_prompt() -> str:
    """
    组装包含当前工作区根路径的系统提示词片段，供注入智能体。
    """
    workspace_dir = get_workspace_path()
    return (
        f"### 【系统运行环境与工作区约束】\n"
        f"- 当前工作区根目录 (绝对路径): `{workspace_dir}`\n"
        f"- 所有的文件检索、目录扫描、产物（正文、三线表、图表等）保存与落盘操作，均必须基于此工作区根目录进行相对路径或绝对路径操作。\n"
        f"- 严禁越界修改或访问工作区以外的系统敏感目录。"
    )


if __name__ == "__main__":
    print("工作区根路径:", get_workspace_path())
    print("\n提示词片段预览:\n" + get_workspace_prompt())

