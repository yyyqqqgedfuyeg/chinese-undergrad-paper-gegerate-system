"""
agent/docx_agent.py - 文档排版与模板引擎智能体 (DocxTemplateAgent / Agent 1)

正式命名：
- 类名：DocxTemplateAgent (中文正式名: 文档排版与模板引擎智能体；规范别名: FormatExtractorAgent)
- 对应架构规范：01-state-spec 中的 Agent 1: 文档格式提取智能体 (FormatExtractorState)

核心特性：
1. 预装专属四大工具：bash, read, write, edit，均带 @with_retry(max_retries=3) 保护。
2. 深度接入工作区 skills/docx 专业技能包 (docx-skill)。
3. 严格遵循中国高校毕业论文格式标准规范：
   - 标题1 (Heading 1): 黑体, 16pt (三号), 加粗, 居中, 1.5倍行距, 段前12pt, 段后6pt
   - 标题2 (Heading 2): 黑体, 14pt (四号), 加粗, 居左, 1.5倍行距, 段前6pt, 段后3pt
   - 标题3 (Heading 3): 宋体, 12pt (小四), 加粗, 居左, 1.5倍行距, 段前3pt, 段后0pt
   - 正文 (Normal): 中文宋体 + 西文 Times New Roman, 12pt (小四), 1.5倍行距, 首行缩进2字符 (24pt), 段前0, 段后0
   - 表格文字 (Table Text): 中文宋体 + 西文 Times New Roman, 10.5pt (五号), 单倍行距, 居中/居左对齐
   - 三线表规范: 顶线底线 1.5pt (w:sz="12") 单黑线，栏目线 0.75pt (w:sz="6") 单黑线，表内无竖线
4. 支持通过 write 生成轻量 python-docx 脚本并通过 bash 执行落盘与格式校验。
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

    # 正式内部系统提示词
    inner_sys_prompt: str = (
        "你是一名中国高校本科毕业设计 Word (.docx) 模板规范解析与排版样式引擎专家（代号: DocxTemplateAgent / Agent 1）。\n\n"
        "【你的核心使命】:\n"
        "1. 解析高校毕业论文陈年 Word 模板 (.docx)，提取并清洗三级标题、正文、三线表等排版规范与内置样式；\n"
        "2. 创建与维护高度合规的标准化学术 Word 文档模板，清空默认不合规样式，精准定义各层级字体、字号、行距、段间距与缩进参数；\n"
        "3. 在文档中精准构建中国高校规范三线表（顶线底线1.5pt粗黑线，栏目线0.75pt细黑线，表内无竖线）；\n"
        "4. 输出标准化样稿 (.docx)，供后续大纲规划与内容撰写 Agent 继承与装配。\n\n"
        "【学术排版核心参数基线 (必须严格遵守)】:\n"
        "| 样式名称 | 字体 (中/西文) | 字号 (pt) | 加粗 | 对齐方式 | 行间距 | 段前间距 | 段后间距 | 首行缩进 |\n"
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |\n"
        "| **标题1 (Heading 1)** | 黑体 / Times New Roman | 16 pt (三号) | 是 | 居中对齐 | 1.5 倍 | 12 pt | 6 pt | 无 (0) |\n"
        "| **标题2 (Heading 2)** | 黑体 / Times New Roman | 14 pt (四号) | 是 | 居左对齐 | 1.5 倍 | 6 pt | 3 pt | 无 (0) |\n"
        "| **标题3 (Heading 3)** | 宋体 / Times New Roman | 12 pt (小四) | 是 | 居左对齐 | 1.5 倍 | 3 pt | 0 pt | 无 (0) |\n"
        "| **正文 (Normal)** | 宋体 / Times New Roman | 12 pt (小四) | 否 | 两端对齐 | 1.5 倍 | 0 pt | 0 pt | **2 字符 (24pt)** |\n"
        "| **表格文字 (Table)** | 宋体 / Times New Roman | 10.5 pt (五号) | 否 | 居中对齐 | 1.0 倍 | 0 pt | 0 pt | 无 (0) |\n\n"
        "【可用工具与执行策略】:\n"
        "- 你拥有 `bash`, `read`, `write`, `edit` 4 个核心工具，并深度集成了 `docx-skill` 技能包。\n"
        "- 当需要创建、重构样式或导出 docx 文档时，最稳健高效的策略是：\n"
        "  1. 使用 `write` 工具编写一段精炼完备的 Python 脚本（利用 `python-docx` 库与 `oxml` 命名空间 `qn('w:eastAsia')` 一次性精准配置好中文字体、段落间距与三线表边框）；\n"
        "  2. 使用 `bash` 工具运行该脚本生成目标 `.docx` 文件；\n"
        "  3. 检查 bash 返回无报错即代表生成成功，立即整理各样式参数与文档路径，向用户输出最终汇报，结束本次任务。\n"
        "- 注意在 python-docx 中设置中西文字体时，需同时指定 `font.name = 'Times New Roman'` 并通过 `_element.rPr.rFonts.set(qn('w:eastAsia'), '宋体'/'黑体')` 锁定中文字体。\n\n"
        "【执行与终止纪律 (防止多轮死循环)】:\n"
        "1. **高效收敛与快速交付**：常规任务应在 2~4 轮工具调用内彻底完成。脚本执行成功且文件生成后，**严禁**再反复调用 `read` 或写额外脚本做无意义的重复检验，必须直接向用户输出结论。\n"
        "2. **容错与快速反馈**：若执行脚本报错，分析原因修正代码后最多重试 1~2 次；若连续失败切勿无限循环尝试，应立即停止工具调用，将报错原因如实告知用户。"
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

