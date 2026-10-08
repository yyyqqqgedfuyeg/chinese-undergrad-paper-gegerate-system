"""
agent/docx_agent.py - 文档排版与模板引擎智能体 (DocxTemplateAgent / Agent 1)

正式命名：
- 类名：DocxTemplateAgent (中文正式名: 文档排版与模板引擎智能体；规范别名: FormatExtractorAgent)
- 对应架构规范：01-state-spec 中的 Agent 1: 文档格式提取智能体 (FormatExtractorState)

核心特性：
1. 预装专属四大工具：bash, read, write, edit，均带 @with_retry(max_retries=3) 保护。
2. 深度接入工作区 skills/docx 专业技能包 (docx-skill)。
3. 根据学校模板提取格式，使用 skill 中的模板流水线保存干净模板和字体样式。
4. 对照源模板验证部件、受保护结构、清洗计划和渲染结果。
"""

from typing import Any, Dict, List, Optional
from langchain_core.tools import BaseTool

from .agent import BaseReActAgent, Skill
from .state import FormatExtractorState
from .tool import AGENT_1_TOOLS, bash, edit, get_docx_skill, read, write


class DocxTemplateAgent(BaseReActAgent):
    """
    Agent 1: 文档排版与模板引擎智能体 (DocxTemplateAgent / FormatExtractorAgent)
    """

    # Template-specific rules live in the skill, not a competing formatting baseline.
    inner_sys_prompt: str = (
        "你是 Word 模板提取与排版智能体。根据用户提供的模板和已挂载 docx skill 执行任务。"
        "先检查原文和实际格式，保留学校模板的分节、页眉页脚、域、图片和样式。"
        "模板内明确的文字要求与实际格式冲突时，记录证据与采用的规则。"
        "使用 skill 的可复用脚本完成提取、复刻、清洗、填写和验证。"
        "只有验证证据支持时才能报告成功；文件生成不等于合规。"
        "报告验证范围、格式冲突与字体替代等未解决限制。"
        "完成 skill 要求的验证和填写后直接汇报；外层负责的独立验收不重复实现。"
        "工具报错时修复后重试，连续三次同类失败应停止并报告错误。"
    )

    state_schema = FormatExtractorState

    def __init__(
        self,
        inner_sys_prompt: Optional[str] = None,
        tools: Optional[List[BaseTool]] = None,
        skills: Optional[List[Skill]] = None,
        **kwargs,
    ):
        # 默认挂载 Agent 1 专属四大工具与 docx 技能
        agent1_tools = tools if tools is not None else list(AGENT_1_TOOLS)
        agent1_skills = skills if skills is not None else [get_docx_skill()]

        super().__init__(
            inner_sys_prompt=inner_sys_prompt,
            tools=agent1_tools,
            skills=agent1_skills,
            **kwargs,
        )

    def get_system_prompt(self, state: Dict[str, Any]) -> str:
        base_prompt = super().get_system_prompt(state)

        # 动态补充 Agent 1 专有上下文
        extra_info: List[str] = []
        raw_doc = state.get("raw_doc_path")
        if raw_doc:
            extra_info.append(f"\n- 原始学校模板路径: `{raw_doc}`")
        new_template = state.get("new_template_path")
        if new_template:
            extra_info.append(f"\n- 输出清洗后模板路径: `{new_template}`")

        if extra_info:
            return base_prompt + "\n\n### 【当前任务模板路径配置】" + "".join(extra_info)

        return base_prompt


# 规范别名
FormatExtractorAgent = DocxTemplateAgent


if __name__ == "__main__":
    agent = DocxTemplateAgent()
    print("Agent 1 初始化成功！正式名称:", DocxTemplateAgent.__name__)
    print("可用工具集:", [t.name for t in agent.get_all_tools()])
    print("挂载技能集:", [s.name for s in agent.get_skills()])

