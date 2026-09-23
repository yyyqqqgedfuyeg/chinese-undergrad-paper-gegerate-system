"""
agent/state.py - 全局状态与智能体专有状态定义规范 (01-state-spec)

基于 LangGraph 的高校毕业论文生成系统的状态机设计：
1. PaperGlobalState: 系统全局共享状态（基础路径、唯一事实源、文献池、元数据）。
2. FormatExtractorState: Agent 1 (DocxTemplateAgent / 文档排版与模板引擎智能体) 专有状态。
3. 辅助工厂函数：自动注入 utils.get_workspace_path() 作为默认工作区路径。
"""

import operator
from typing import Annotated, Any, Dict, List, Optional, Sequence
from typing_extensions import TypedDict
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

try:
    from .utils.get_sys_path import get_workspace_path
except ImportError:
    from agent.utils.get_sys_path import get_workspace_path


# ==============================================================================
# 1. 全局共享状态 (PaperGlobalState)
# ==============================================================================
class PaperGlobalState(TypedDict, total=False):
    """
    系统全局共享状态。
    【设计原则】只保留具备全局、跨阶段持久价值的基础设施路径与核心事实资产，严禁容纳单步临时变量。
    """
    # 1. 基础配置与目录
    raw_doc_path: str                 # 1. 原文档/学校模板地址 (.docx)
    new_template_path: str            # 2. 新模板的文件地址（提取并标准化后的模板）
    workspace_dir: str                # 3. 本次任务工作区根目录（默认自动读取 utils.get_workspace_path()）

    # 2. 核心学术资产与唯一事实源
    single_source_of_truth: Dict[str, Any]  # 唯一事实源（技术栈、数据库实体Schema、功能设计、实验方法）
    bib_pool: List[Dict[str, Any]]          # 文献池（20-25篇真实中英文献元数据及引用 Key）

    # 3. 项目元信息
    project_id: str                   # 项目唯一标识
    topic: str                        # 论文题目


def create_initial_global_state(
    topic: str = "",
    raw_doc_path: str = "",
    new_template_path: str = "",
    project_id: str = "paper_project_default",
    workspace_dir: Optional[str] = None,
    single_source_of_truth: Optional[Dict[str, Any]] = None,
    bib_pool: Optional[List[Dict[str, Any]]] = None,
) -> PaperGlobalState:
    """
    便捷工厂函数：创建并初始化 PaperGlobalState
    自动使用 utils.get_workspace_path() 填充 workspace_dir。
    """
    return {
        "raw_doc_path": raw_doc_path,
        "new_template_path": new_template_path,
        "workspace_dir": workspace_dir or get_workspace_path(),
        "single_source_of_truth": single_source_of_truth or {},
        "bib_pool": bib_pool or [],
        "project_id": project_id,
        "topic": topic,
    }


# ==============================================================================
# 2. Agent 1 专有状态：文档格式与模板提取 (FormatExtractorState)
# ==============================================================================
class FormatExtractorState(TypedDict):
    """
    Agent 1 (DocxTemplateAgent) 专有状态：
    - messages: 对话流与推理记录
    - content: 提取出的文本/段落切片内容流（只追加 Append-Only）
    - template: 提炼出的模板与内置样式配置字典
    - total_tokens / prompt_tokens / completion_tokens: Token 指标
    - total_duration_seconds: 运行耗时
    """
    messages: Annotated[Sequence[BaseMessage], add_messages]
    content: Annotated[List[str], operator.add]
    template: Dict[str, Any]
    total_tokens: Annotated[int, operator.add]
    prompt_tokens: Annotated[int, operator.add]
    completion_tokens: Annotated[int, operator.add]
    total_duration_seconds: float


if __name__ == "__main__":
    initial_state = create_initial_global_state(topic="基于微服务架构的高校心理咨询预约系统的设计与实现")
    print("PaperGlobalState 初始化成功:")
    for k, v in initial_state.items():
        print(f"  - {k}: {v}")

