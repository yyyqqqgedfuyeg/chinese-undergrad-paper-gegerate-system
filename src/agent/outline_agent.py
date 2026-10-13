"""无工具大纲 agent：生成、校验完整三级标题规划，再提交到全局 state。"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from .agent import BaseReActAgent
from .state import PaperGlobalState
from .paper_routing import agent_prompt, resolve_paper_profile
from .output_parsers import OutlineOutput, parse_outline_output
from .output_parsers.outline_normalization import normalize_workflow_outline


class OutlineAgent:
    """单节点 LangGraph；没有工具/技能注册入口，也不使用工具式结构化输出。

    invoke 接收全局 state，成功后原地更新 outline_plan 并返回该 state。
    graph 可直接嵌入上层 LangGraph，失败时不提交未经校验的结果。
    """

    state_schema = PaperGlobalState
    inner_sys_prompt = agent_prompt("outline", {"paper_type": "software"})

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
            "paper_profile": resolve_paper_profile(state),
            "single_source_of_truth": state.get("single_source_of_truth", {}),
        }
        from .research import digest
        from .writing.storage import atomic_write
        draft_path = Path(state["workspace_dir"]) / "outline/proposal.json" if state.get("workspace_dir") and state.get("research_lock") else None
        identity = digest(context)
        previous = None
        if draft_path and draft_path.exists():
            cached = json.loads(draft_path.read_text())
            if cached.get("input_sha256") == identity:
                previous = cached["content"]
        def parse_candidate(candidate):
            # Independent OutlineAgent remains strict and side-effect free unless
            # invoked under a frozen full workflow.
            if state.get("research_lock") and isinstance(candidate, str):
                normalized, report = normalize_workflow_outline(candidate)
                parsed = parse_outline_output(normalized, state)
                if report:
                    parsed["outline_normalization_report"] = report
                return parsed
            return parse_outline_output(candidate, state)

        messages = [SystemMessage(content=agent_prompt("outline", state) + "\nJSON Schema:\n" + json.dumps(
                OutlineOutput.model_json_schema(), ensure_ascii=False)),
            HumanMessage(content=json.dumps(context, ensure_ascii=False))]
        if previous is not None:
            try:
                return parse_candidate(previous)
            except ValueError as exc:
                messages.append(HumanMessage(content="上次大纲未提交，请在以下草稿基础上修复校验错误并控制总字数约12000："
                    + str(exc)[:3000] + "\n" + previous))
        for attempt in range(3):
            response = self._model.invoke(messages)
            if draft_path and isinstance(response.content, str):
                atomic_write(draft_path, json.dumps({"input_sha256": identity, "content": response.content}, ensure_ascii=False))
            try:
                return parse_candidate(response.content) if state.get("research_lock") and not response.tool_calls else parse_outline_output(response, state)
            except ValueError as exc:
                if attempt == 2:
                    raise
                messages.append(HumanMessage(content="大纲校验未通过，请修复后重新输出完整JSON，禁止四级标题："
                    + str(exc)[:3000] + "\n上一稿：" + str(response.content)))

    def invoke(
        self, state: PaperGlobalState, config: Optional[Dict[str, Any]] = None,
    ) -> PaperGlobalState:
        self._validate_input(state)
        result = self.graph.invoke(state, config=config)
        state["outline_plan"] = result["outline_plan"]
        if "outline_normalization_report" in result:
            state["outline_normalization_report"] = result["outline_normalization_report"]
        return state


GlobalPlannerAgent = OutlineAgent
