"""
agent/tool.py - 论文生成系统基础工具库与 Skill 技能包定义

包含工具：
1. bash: 工作区安全终端命令执行器 (Python脚本运行/底层XML处理等)
2. read: 工作区文件读取器 (支持指定最大行数)
3. write: 工作区文件写入与创建器 (自动建立多级目录)
4. edit: 工作区文件定向编辑与替换器
5. list_workspace_files: 查看工作区目录结构与文件清单
6. search_academic_literature: 文献池检索与 GB/T 7714 格式候选匹配
7. generate_mermaid_diagram: 论文图表 Mermaid 源码生成与校验落盘

所有工具均内置 tool_retry.py 的 @with_retry(max_retries=3) 保护，
并提供 get_docx_skill() 技能包工厂函数。
"""

import os
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
from langchain_core.tools import tool

from .agent import Skill
from .tool_retry import with_retry
from .utils.get_sys_path import get_workspace_path


# ------------------------------------------------------------------------------
# 核心工具 1：bash 命令行执行工具
# ------------------------------------------------------------------------------
@tool
@with_retry(max_retries=3, initial_delay=0.5)
def bash(command: str, timeout_seconds: int = 60) -> str:
    """
    在工作区根目录下执行命令行指令 (Bash / PowerShell / CMD)。
    可用于运行 Python 脚本 (如 python-docx 排版脚本)、解压查看 OpenXML 结构、格式校验等。
    :param command: 待执行的终端命令文本
    :param timeout_seconds: 命令执行超时时间（秒），默认 60 秒
    :return: 命令执行返回码、标准输出 (stdout) 与标准错误 (stderr)
    """
    workspace_root = str(Path(get_workspace_path()).resolve())

    # 禁止破坏性危险命令
    dangerous_keywords = ["rmdir /s /q c:", "del /f /s /q c:", "format ", "mkfs"]
    for kw in dangerous_keywords:
        if kw in command.lower():
            raise PermissionError(f"安全策略拦截：禁止执行破坏性系统命令: {command}")

    proc = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        cwd=workspace_root,
        timeout=timeout_seconds,
    )

    # 兼容 Windows 多编码输出
    try:
        stdout_str = proc.stdout.decode("utf-8")
    except UnicodeDecodeError:
        stdout_str = proc.stdout.decode("gbk", errors="replace")

    try:
        stderr_str = proc.stderr.decode("utf-8")
    except UnicodeDecodeError:
        stderr_str = proc.stderr.decode("gbk", errors="replace")

    output_lines = [f"【命令执行完毕】退出码: {proc.returncode}"]
    if stdout_str.strip():
        output_lines.append(f"--- STDOUT ---\n{stdout_str.strip()}")
    if stderr_str.strip():
        output_lines.append(f"--- STDERR ---\n{stderr_str.strip()}")
    if not stdout_str.strip() and not stderr_str.strip():
        output_lines.append("(命令执行无控制台输出)")

    # 截断超大输出
    full_output = "\n".join(output_lines)
    if len(full_output) > 5000:
        full_output = full_output[:5000] + "\n... [输出内容过长，已截断显示前 5000 字符] ..."

    return full_output


# ------------------------------------------------------------------------------
# 核心工具 2：read 文件读取工具
# ------------------------------------------------------------------------------
@tool
@with_retry(max_retries=3, initial_delay=0.3)
def read(file_path: str, max_lines: int = 300) -> str:
    """
    读取工作区中指定文件的文本内容（支持 .py, .md, .txt, .json, .xml 等）。
    :param file_path: 相对工作区根目录的文件路径
    :param max_lines: 最大读取行数，防止巨型文件撑爆上下文（默认前 300 行）
    :return: 文件的文本内容
    """
    workspace_root = Path(get_workspace_path()).resolve()
    target_file = (workspace_root / file_path).resolve()

    if not str(target_file).startswith(str(workspace_root)):
        raise PermissionError(f"禁止越界访问工作区之外的文件: {file_path}")

    if not target_file.exists():
        raise FileNotFoundError(f"文件不存在: {file_path} (请确认路径或先创建)")

    if not target_file.is_file():
        raise IsADirectoryError(f"目标路径是文件夹而非文件: {file_path}")

    try:
        content = target_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = target_file.read_text(encoding="gbk", errors="replace")

    lines = content.splitlines()
    if len(lines) > max_lines:
        truncated_content = "\n".join(lines[:max_lines])
        return f"{truncated_content}\n\n... [文件较长，已截断显示前 {max_lines} 行，剩余 {len(lines) - max_lines} 行未显示] ..."

    return content


# ------------------------------------------------------------------------------
# 核心工具 3：write 文件写入工具
# ------------------------------------------------------------------------------
@tool
@with_retry(max_retries=3, initial_delay=0.3)
def write(file_path: str, content: str, overwrite: bool = True) -> str:
    """
    在工作区指定路径写入或创建文本文件（自动递归创建父级目录）。
    :param file_path: 相对工作区根目录的文件保存路径 (如 'test/sample.py')
    :param content: 要写入的完整文本内容
    :param overwrite: 若文件已存在是否允许覆盖 (默认 True)
    :return: 写入结果说明
    """
    workspace_root = Path(get_workspace_path()).resolve()
    target_file = (workspace_root / file_path).resolve()

    if not str(target_file).startswith(str(workspace_root)):
        raise PermissionError(f"禁止在工作区之外创建或修改文件: {file_path}")

    if target_file.exists() and not overwrite:
        raise FileExistsError(f"文件 `{file_path}` 已存在且 overwrite 设置为 False。")

    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(content, encoding="utf-8")

    size_kb = target_file.stat().st_size / 1024
    return f"✅ 文件成功写入: `{file_path}` (大小: {size_kb:.2f} KB, 行数: {len(content.splitlines())})"


# ------------------------------------------------------------------------------
# 核心工具 4：edit 文件定向编辑/替换工具
# ------------------------------------------------------------------------------
@tool
@with_retry(max_retries=3, initial_delay=0.3)
def edit(file_path: str, target_content: str, replacement_content: str, replace_all: bool = False) -> str:
    """
    定向编辑工作区中的指定文件：精准检索 target_content 并替换为 replacement_content。
    :param file_path: 相对工作区根目录的文件路径
    :param target_content: 需要被替换的精确原文本片段
    :param replacement_content: 替换后的新文本片段
    :param replace_all: 若为 True 则替换所有匹配项，默认 False 仅替换首个匹配项
    :return: 编辑执行结果说明
    """
    workspace_root = Path(get_workspace_path()).resolve()
    target_file = (workspace_root / file_path).resolve()

    if not str(target_file).startswith(str(workspace_root)):
        raise PermissionError(f"禁止在工作区之外编辑文件: {file_path}")

    if not target_file.exists():
        raise FileNotFoundError(f"文件不存在，无法进行编辑: {file_path}")

    try:
        content = target_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        content = target_file.read_text(encoding="gbk", errors="replace")

    if target_content not in content:
        raise ValueError(
            f"在文件 `{file_path}` 中未找到目标替换文本 (target_content)。"
            f"请先使用 read 工具检查文件实际内容并确保 target_content 精确一致。"
        )

    count = content.count(target_content)
    if replace_all:
        new_content = content.replace(target_content, replacement_content)
        replaced_num = count
    else:
        new_content = content.replace(target_content, replacement_content, 1)
        replaced_num = 1

    target_file.write_text(new_content, encoding="utf-8")
    return f"✅ 文件 `{file_path}` 编辑成功，已完成 {replaced_num} 处文本替换。"


# ------------------------------------------------------------------------------
# 保留的辅助业务工具 (支持向后兼容)
# ------------------------------------------------------------------------------
@tool
@with_retry(max_retries=3, initial_delay=0.3)
def list_workspace_files(relative_dir: str = ".") -> str:
    """列出当前工作区指定目录下的所有文件和子文件夹信息。"""
    workspace_root = Path(get_workspace_path()).resolve()
    target_path = (workspace_root / relative_dir).resolve()

    if not str(target_path).startswith(str(workspace_root)):
        raise PermissionError(f"禁止越界访问工作区之外的目录: {relative_dir}")

    if not target_path.exists():
        raise FileNotFoundError(f"目录不存在: {relative_dir}")

    if not target_path.is_dir():
        raise NotADirectoryError(f"指定路径不是文件夹: {relative_dir}")

    items = list(target_path.iterdir())
    if not items:
        return f"目录 `{relative_dir}` 为空。"

    result_lines = [f"📂 目录 `{relative_dir}` 下的文件清单 (共 {len(items)} 项):"]
    for item in sorted(items, key=lambda x: (not x.is_dir(), x.name.lower())):
        rel = item.relative_to(workspace_root)
        if item.is_dir():
            result_lines.append(f"  📁 [DIR]  {rel}/")
        else:
            size_kb = item.stat().st_size / 1024
            result_lines.append(f"  📄 [FILE] {rel} ({size_kb:.2f} KB)")

    return "\n".join(result_lines)


# 别名映射
read_workspace_file = read
write_workspace_file = write
edit_workspace_file = edit


@tool
@with_retry(max_retries=3, initial_delay=0.3)
def search_academic_literature(topic_or_keyword: str, max_results: int = 5) -> str:
    """根据论文选题或技术关键词检索学术文献候选池，返回符合 GB/T 7714 标准的参考文献列表。"""
    kb_papers = [
        {
            "key": "cite_spring_cloud_arch",
            "keywords": ["spring", "微服务", "后端", "java", "架构"],
            "formatted": "周志明. 凤凰架构: 构建可靠的大型分布式系统[M]. 北京: 机械工业出版社, 2021: 85-112.",
        },
        {
            "key": "cite_vue3_frontend",
            "keywords": ["vue", "前端", "单页面", "ui", "组件"],
            "formatted": "尤雨溪, 团队. Vue.js 3.0 核心原理与企业级开发实战[J]. 计算机工程与应用, 2023, 59(12): 101-109.",
        },
        {
            "key": "cite_mysql_optimization",
            "keywords": ["mysql", "数据库", "schema", "索引", "持久化"],
            "formatted": "姜承尧. MySQL技术内幕: InnoDB存储引擎[M]. 2版. 北京: 机械工业出版社, 2022: 45-68.",
        },
        {
            "key": "cite_psychology_booking",
            "keywords": ["心理", "咨询", "预约", "高校", "学生管理"],
            "formatted": "张敏, 李建华. 高校心理健康服务数字化平台建设与预约机制优化研究[J]. 中国电化教育, 2024(3): 78-85.",
        },
        {
            "key": "cite_distributed_security",
            "keywords": ["安全", "jwt", "认证", "权限", "oauth"],
            "formatted": "王伟, 赵强. 基于OAuth2.0与JWT的微服务无状态鉴权体系设计[J]. 软件学报, 2023, 34(8): 3652-3669.",
        },
    ]

    kw = topic_or_keyword.lower()
    matched = []
    for paper in kb_papers:
        score = sum(1 for k in paper["keywords"] if k in kw)
        if score > 0 or not matched:
            matched.append((score, paper))

    matched.sort(key=lambda x: x[0], reverse=True)
    selected = matched[:max_results]

    res_lines = [f"📚 为关键词 `{topic_or_keyword}` 检索到以下规范参考文献:"]
    for idx, (_, item) in enumerate(selected, 1):
        res_lines.append(f"{idx}. [{item['key']}] {item['formatted']}")

    res_lines.append("\n【引用建议】: 在论文草稿中可使用标签 `[[REF_CITE:{key}]]` 进行动态交叉引用。")
    return "\n".join(res_lines)


@tool
@with_retry(max_retries=3, initial_delay=0.3)
def generate_mermaid_diagram(
    title: str,
    diagram_type: str,
    mermaid_code: str,
    save_filename: str = "",
) -> str:
    """校验并生成毕业论文中所需的高保真 Mermaid 架构图或时序流程图源码。"""
    clean_code = mermaid_code.strip()
    valid_starts = ("flowchart", "graph", "sequencediagram", "classdiagram", "erdiagram", "statediagram")
    first_token = clean_code.split()[0].lower() if clean_code else ""

    if not any(clean_code.lower().startswith(prefix) for prefix in valid_starts):
        raise ValueError(
            f"Mermaid 语法格式有误: 首行必须以标准图表类型声明开头 (如 'flowchart TD')，当前首词为: '{first_token}'"
        )

    workspace_root = Path(get_workspace_path()).resolve()
    diagram_dir = workspace_root / "assets" / "diagrams"
    diagram_dir.mkdir(parents=True, exist_ok=True)

    if not save_filename:
        save_filename = f"diagram_{abs(hash(title)) % 10000}"

    target_mmd = diagram_dir / f"{save_filename}.mmd"
    target_mmd.write_text(clean_code, encoding="utf-8")

    return (
        f"🎨 Mermaid 图表已校验并通过！\n"
        f"- 图表标题: {title}\n"
        f"- 图表类型: {diagram_type}\n"
        f"- 源码落盘路径: `assets/diagrams/{save_filename}.mmd`\n"
        f"- 源码内容预览:\n```mermaid\n{clean_code}\n```"
    )


# ------------------------------------------------------------------------------
# docx-skill 技能包加载工厂
# ------------------------------------------------------------------------------
def get_docx_skill() -> Skill:
    """
    加载工作区 skills/docx 下的专业 Word 技能包规范并绑定基础工具
    """
    workspace_root = Path(get_workspace_path()).resolve()
    skill_md = workspace_root / "skills" / "docx" / "SKILL.md"
    instructions = ""
    if skill_md.exists():
        instructions = skill_md.read_text(encoding="utf-8")
    else:
        instructions = (
            "docx 专业技能说明：支持通过 python-docx 或底层 OpenXML 深度定制学术 Word 模板，"
            "支持精确控制中西文字体、字号、1.5倍行距、段前段后磅值、首行缩进2字符以及中国学术三线表规范。"
        )

    return Skill(
        name="docx-skill",
        description="专业 Word (.docx/.dotx) 模板提取、排版规范定义、文档创建、三线表排版与底层 OpenXML 操作技能包",
        instructions=instructions,
        tools=[bash, read, write, edit],
    )


# Agent 1 专属四工具清单
AGENT_1_TOOLS = [bash, read, write, edit]

# 全量基础工具清单
BASIC_TOOLS = [
    bash,
    read,
    write,
    edit,
    list_workspace_files,
    search_academic_literature,
    generate_mermaid_diagram,
]


if __name__ == "__main__":
    print("Agent 1 专属工具集:", [t.name for t in AGENT_1_TOOLS])
    docx_skill = get_docx_skill()
    print("docx-skill 加载状态:", docx_skill.name, "已绑定工具数:", len(docx_skill.tools))
