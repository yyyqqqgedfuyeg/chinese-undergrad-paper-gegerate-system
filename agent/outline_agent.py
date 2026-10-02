"""无工具大纲 agent：生成、校验完整三级标题规划，再提交到全局 state。"""

import json
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from .agent import BaseReActAgent
from .state import PaperGlobalState
from .output_parsers import OutlineOutput, parse_outline_output


class OutlineAgent:
    """单节点 LangGraph；没有工具/技能注册入口，也不使用工具式结构化输出。

    invoke 接收全局 state，成功后原地更新 outline_plan 并返回该 state。
    graph 可直接嵌入上层 LangGraph，失败时不提交未经校验的结果。
    """

    state_schema = PaperGlobalState
    inner_sys_prompt = (
        "你是中国高校本科毕业论文大纲规划专家。根据题目和已有唯一事实源，"
        "制定包含章标题、二级标题和三级标题的完整论文大纲，覆盖绪论、相关理论技术、需求分析、"
        "设计、实现、测试、总结等适用内容。已有事实源是约束，不得改变技术栈或业务事实。"
        "你没有任何工具，只输出 JSON 对象，其唯一字段为 outline_plan。"
        "每个标题节点只包含 section_id、title、target_words、status、planned_assets。"
        "outline_plan 是按目录先序排列的扁平列表，必须包含所有层级的标题节点，不能一上来就是 1.1。"
        "section_id 支持 1（章）、1.1（二级）、3.1.1（三级），唯一且按章节数字升序排列。"
        "第一条必须是 section_id=1、title=第一章 绪论；每章都有真实章标题，如 第四章 系统设计。"
        "每个二级标题前必须有所属章标题，每个三级标题前必须有所属二级标题。"
        "第一、二章只细分到二级标题。第三章及以后涉及系统需求分析、系统设计、数据库设计、"
        "系统实现、系统测试的核心章节必须展开三级标题；按业务模块、设计对象和测试类型细化，"
        "不能只用一个三级标题敷衍整个章节。总结与展望等非核心章节可以只到二级。"
        "title 为非空标题；有子标题的章或二级节点 target_words=0，字数只分配到叶子小节，"
        "叶子小节 target_words 为正整数，避免父子字数重复计算；status 固定为 pending。"
        "planned_assets 为图表需求字符串列表（如 fig_4_1 (系统架构图)、"
        "tbl_6_1 (测试用例三线表)），无需图表时使用空列表。"
        "如果题目涉及软件开发系统，数据库设计必须细分到三级，至少包括概念结构设计和逻辑结构/数据表设计。"
        "必须在对应叶子小节 planned_assets 中规划系统 ER 图（实体、主外键和关系），"
        "以及实际数据库数据表的结构三线表（字段名、类型、主外键、约束、说明），两者缺一不可。"
        "数据表必须按核心实体分别列出具体表名和图表标识，不能用一项笼统的 数据表 汇总代替。"
        "若已有事实源提供 db_schemas，必须覆盖其中每张数据表；否则按题目规划核心实体表，"
        "但不修改事实源。ER 图和数据库表结构应归属数据库设计小节，不能用业务流程图或测试用例表替代。"
        "只规划图表和测试方法，不编造已完成的实验结果，不生成正文、文献、"
        "事实源或文件，不附加解释或 Markdown 代码块。"
    )

    def __init__(self, llm: Optional[Any] = None):
        self.llm = llm if llm is not None else BaseReActAgent._create_default_llm(temperature=None)
        # JSON mode 不会向模型提供 tools 或 function calling schema。
        self._model = self.llm.bind(response_format={"type": "json_object"})
        workflow = StateGraph(self.state_schema)
        workflow.add_node("generate_outline", self._generate_outline)
        workflow.add_edge(START, "generate_outline")
        workflow.add_edge("generate_outline", END)
        self.graph = workflow.compile()

    @staticmethod
    def _validate_input(state: PaperGlobalState) -> None:
        topic = state.get("topic")
        if not isinstance(topic, str) or not topic.strip():
            raise ValueError("生成大纲需要非空 topic")

    def _generate_outline(self, state: PaperGlobalState) -> Dict[str, Any]:
        self._validate_input(state)
        context = {
            "topic": state["topic"],
            "single_source_of_truth": state.get("single_source_of_truth", {}),
        }
        response = self._model.invoke([
            SystemMessage(content=self.inner_sys_prompt + "\nJSON Schema:\n" + json.dumps(
                OutlineOutput.model_json_schema(), ensure_ascii=False
            )),
            HumanMessage(content=json.dumps(context, ensure_ascii=False)),
        ])
        return parse_outline_output(response, state)

    def invoke(
        self, state: PaperGlobalState, config: Optional[Dict[str, Any]] = None,
    ) -> PaperGlobalState:
        self._validate_input(state)
        result = self.graph.invoke(state, config=config)
        state["outline_plan"] = result["outline_plan"]
        return state


GlobalPlannerAgent = OutlineAgent
