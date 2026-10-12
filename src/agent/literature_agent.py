"""只挂载一个文献搜索工具的 LangGraph agent node。"""

import json

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from .agent import BaseReActAgent
from .literature_tool import LiteratureSearchError, PublicationYearRange, SearchQueries, create_literature_tool
from .output_parsers.literature_parser import parse_literature_output, title_identity
from .state import PaperGlobalState


class LiteratureAgent:
    state_schema = PaperGlobalState
    inner_sys_prompt = (
        "你是本科论文文献检索专家。只调用 search_academic_literature 工具，不能自行生成文献。"
        "根据题目、事实源和大纲提炼 3-4 个互补中文主题关键词及 2-3 个英文检索短语。"
        "中文关键词应短而准确，覆盖核心业务、研究对象、技术方法；勿照搬完整题目，"
        "不要添加与主题无关的关键词凑数。英文关键词使用自然英文，不能只搜索中国地区。"
        "例如心理咨询预约系统可检索 心理咨询、大学生心理健康、预约系统，"
        "以及 online counseling、university mental health、appointment scheduling。"
        "工具负责从全球文献索引获取 15 篇中文和 5 篇英文并校验；"
        "不足时根据工具反馈调整关键词。每次仅调用一次该工具。"
        "多轮依次探索：核心主题、同义词及术语变体、应用场景及研究对象、相关技术与方法。"
        "每轮必须提供尚未检索的新关键词；所有方向都必须与论文题目紧密相关。"
        "工具要求关键词出现在论文标题中，请优先用短主题词（中文约2-6字，英文2-3词），"
        "不要堆叠多个限定词；例如心理咨询、心理健康、预约系统，以及 online counseling、appointment scheduling。"
        "publication_year_range 是用户指定的发表年份硬约束，多轮扩词时不得放宽。"
    )

    def __init__(self, llm=None, searcher=None, max_search_rounds=4):
        if not isinstance(max_search_rounds, int) or isinstance(max_search_rounds, bool) or not 2 <= max_search_rounds <= 8:
            raise ValueError("max_search_rounds 必须为 2-8，默认 4")
        self.max_search_rounds = max_search_rounds
        self.llm = llm if llm is not None else BaseReActAgent._create_default_llm(temperature=None)
        self._tool = create_literature_tool(searcher)
        # DeepSeek thinking 模式不支持指定 tool_choice；通过提示词和执行侧白名单约束。
        self._model = self.llm.bind_tools([self._tool], tool_choice="auto")
        workflow = StateGraph(self.state_schema)
        workflow.add_node("search_literature", self._search_literature)
        workflow.add_edge(START, "search_literature")
        workflow.add_edge("search_literature", END)
        self.graph = workflow.compile()

    def get_all_tools(self):
        return [self._tool]

    @staticmethod
    def _validate_input(state):
        if not isinstance(state.get("topic"), str) or not state["topic"].strip():
            raise ValueError("文献检索需要非空 topic")
        if state.get("publication_year_range") is not None:
            PublicationYearRange.model_validate(state["publication_year_range"])

    def _search_literature(self, state):
        self._validate_input(state)
        year_range = (PublicationYearRange.model_validate(state["publication_year_range"])
                      if state.get("publication_year_range") is not None else None)
        messages = [SystemMessage(content=self.inner_sys_prompt), HumanMessage(content=json.dumps(
            {"topic": state["topic"], "single_source_of_truth": state.get("single_source_of_truth", {}),
             "outline_plan": state.get("outline_plan", []),
             "publication_year_range": year_range.model_dump(exclude_none=True) if year_range else None},
            ensure_ascii=False))]
        pool, attempts = [], []
        seen_queries = {"chinese_queries": set(), "english_queries": set()}
        seen_dois, seen_titles = set(), set()
        counts = {"zh": 0, "en": 0}
        for round_number in range(1, self.max_search_rounds + 1):
            response = self._model.invoke(messages)
            calls = response.tool_calls
            if len(calls) != 1 or calls[0]["name"] != self._tool.name:
                # 无合法工具调用时不给模型的文本补写文献权限，继续要求检索。
                attempts.append({"round": round_number, "error": "invalid_tool_call"})
                messages.append(HumanMessage(content="必须且只能调用一次 search_academic_literature；请提供新的中英文关键词。"))
                continue
            call = calls[0]
            try:
                # 执行侧锁定用户配置，防止模型为了配额放宽年份或自行增加限制。
                arguments = SearchQueries.model_validate({**call["args"],
                    "publication_year_range": year_range}).model_dump(exclude_none=True)
                for name in seen_queries:
                    terms = arguments[name]
                    arguments[name] = [q for q in terms if q.casefold() not in seen_queries[name]]
                    if not arguments[name]:
                        raise ValueError("每轮须提供新的中英文关键词，重复关键词不会再次检索")
                for name in seen_queries:
                    seen_queries[name].update(q.casefold() for q in arguments[name])
                output = self._tool.invoke(arguments)
                records = parse_literature_output(output)["bib_pool"]
                for paper in records:
                    if year_range is not None and not year_range.contains(paper["year"]):
                        continue
                    language = paper["language"]
                    title_key = title_identity(paper["title"])
                    if counts[language] >= {"zh": 15, "en": 5}[language]:
                        continue
                    if title_key in seen_titles or paper["doi"] in seen_dois:
                        continue
                    pool.append(paper)
                    counts[language] += 1
                    seen_titles.add(title_key)
                    if paper["doi"]:
                        seen_dois.add(paper["doi"])
                attempts.append({"round": round_number, "queries": arguments,
                                 "counts": dict(counts), "searches": output.get("searches", [])})
                if counts == {"zh": 15, "en": 5}:
                    break
                feedback = f"累计找到 {counts}，目标中文15英文5。请从尚未覆盖的同义词、场景、研究对象、技术方法扩展新关键词。"
            except (LiteratureSearchError, ValueError) as exc:
                feedback = str(exc)
                attempts.append({"round": round_number, "error": feedback})
            messages.extend([response, ToolMessage(content=feedback, tool_call_id=call["id"])])
        pool.sort(key=lambda paper: paper["language"] != "zh")
        return {**parse_literature_output({"bib_pool": pool}), "literature_search_report": {
            "complete": counts == {"zh": 15, "en": 5}, "counts": counts,
            "shortfall": {"zh": 15 - counts["zh"], "en": 5 - counts["en"]},
            "rounds": len(attempts), "max_rounds": self.max_search_rounds,
            "stop_reason": "quota_met" if counts == {"zh": 15, "en": 5} else "round_limit",
            "attempts": attempts,
            "publication_year_range": year_range.model_dump(exclude_none=True) if year_range else None,
        }}

    def invoke(self, state, config=None):
        self._validate_input(state)
        result = self.graph.invoke(state, config=config)
        state["bib_pool"] = result["bib_pool"]
        state["literature_search_report"] = result["literature_search_report"]
        return state


LiteratureIndexerAgent = LiteratureAgent
