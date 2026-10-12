"""模板准备角色：只使用绑定输入的 inspect/build/verify 工具。"""

from typing import Any, Dict, List, Optional
from langchain_core.tools import BaseTool

from .agent import BaseReActAgent, Skill
from .state import FormatExtractorState
from .paper_routing import format_prompt
from .template.tools import create_template_tools
from .security.policy import authorize, reject_extra_tools, role_skill
from .utils.get_sys_path import get_workspace_path


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
        source_path: str | None = None,
        workspace_dir: str | None = None,
        **kwargs,
    ):
        if tools is not None:
            raise PermissionError("模板 agent 的工具只能由角色工厂提供")
        agent1_skills = skills if skills is not None else [role_skill("template")]
        reject_extra_tools(agent1_skills)
        agent1_tools = create_template_tools(source_path, workspace_dir or get_workspace_path())
        if kwargs.get("llm") is None:
            from .writing.models import create_writing_model
            kwargs["llm"] = create_writing_model("KIMI")
        self.source_path = source_path
        self.task_workspace = workspace_dir or get_workspace_path()
        self._registering_role_tools = True

        super().__init__(
            inner_sys_prompt=inner_sys_prompt,
            tools=agent1_tools,
            skills=agent1_skills,
            **kwargs,
        )

        self._registering_role_tools = False

    def register_tool(self, tool_item):
        if not getattr(self, "_registering_role_tools", False):
            raise PermissionError("模板 agent 工具集已封闭")
        authorize("template", tool_item.name)
        super().register_tool(tool_item)

    def register_skill(self, skill):
        reject_extra_tools([skill])
        super().register_skill(skill)

    def get_system_prompt(self, state: Dict[str, Any]) -> str:
        instructions = "\n".join(s.instructions for s in self.get_skills())
        return format_prompt("论文模板提取与验证", self.inner_sys_prompt + "\n" + instructions
                + f"\n只读学校模板：{self.source_path or '未绑定，请由调用方配置'}"
                + f"\n模板输出目录：{self.task_workspace}/template"
                + "\n可用工具：inspect_template、build_template、verify_template。")


# 规范别名
FormatExtractorAgent = DocxTemplateAgent


if __name__ == "__main__":
    agent = DocxTemplateAgent()
    print("Agent 1 初始化成功！正式名称:", DocxTemplateAgent.__name__)
    print("可用工具集:", [t.name for t in agent.get_all_tools()])
    print("挂载技能集:", [s.name for s in agent.get_skills()])

