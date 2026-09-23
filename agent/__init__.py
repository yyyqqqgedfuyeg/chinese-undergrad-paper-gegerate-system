"""
agent 包统一初始化与接口导出
"""

from .agent import BaseReActAgent, Skill, AgentState, AcademicPaperAgent
from .docx_agent import DocxTemplateAgent, FormatExtractorAgent
from .state import PaperGlobalState, FormatExtractorState, create_initial_global_state
from .tool import (
    AGENT_1_TOOLS,
    BASIC_TOOLS,
    bash,
    read,
    write,
    edit,
    list_workspace_files,
    read_workspace_file,
    write_workspace_file,
    edit_workspace_file,
    search_academic_literature,
    generate_mermaid_diagram,
    get_docx_skill,
)
from .tool_retry import with_retry
from .utils.get_sys_path import get_workspace_path, get_workspace_prompt

__all__ = [
    # 智能体基类与核心智能体
    "BaseReActAgent",
    "DocxTemplateAgent",
    "FormatExtractorAgent",
    "AcademicPaperAgent",
    "Skill",
    "AgentState",
    # 状态机规范
    "PaperGlobalState",
    "FormatExtractorState",
    "create_initial_global_state",
    # 工具集
    "AGENT_1_TOOLS",
    "BASIC_TOOLS",
    "bash",
    "read",
    "write",
    "edit",
    "list_workspace_files",
    "read_workspace_file",
    "write_workspace_file",
    "edit_workspace_file",
    "search_academic_literature",
    "generate_mermaid_diagram",
    # 技能包与辅助工具
    "get_docx_skill",
    "with_retry",
    "get_workspace_path",
    "get_workspace_prompt",
]
