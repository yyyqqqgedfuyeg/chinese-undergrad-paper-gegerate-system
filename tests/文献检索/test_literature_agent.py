"""离线回归：配额、部分结果、多轮扩词、单工具边界、来源规范化。"""

import copy
import unittest
from unittest.mock import patch

import httpx
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from agent import LiteratureAgent, PaperGlobalState, create_initial_global_state
from agent.literature_tool import (LiteratureSearcher, PublicationYearRange, create_literature_tool,
                                   matches_query, normalize_record)
from agent.output_parsers import LiteratureRecord, parse_literature_output


def paper(index, language="zh"):
    return {"key": f"cite_{language}_{index}", "title": f"{'心理咨询研究' if language == 'zh' else 'Counseling study'} {index}",
            "authors": "Researcher", "journal": "Journal", "year": 2024, "language": language,
            "language_basis": "provider", "doi": f"10.1234/{language}.{index}",
            "url": f"https://doi.org/10.1234/{language}.{index}", "source": "openalex",
            "source_id": f"https://openalex.org/W{index}", "source_url": f"https://api.openalex.org/W{index}",
            "query": "心理咨询", "retrieved_at": "2026-10-02T00:00:00+00:00"}


class Model:
    def __init__(self, repeat=False):
        self.calls = []
        self.repeat = repeat

    def bind_tools(self, tools, **kwargs):
        self.tools = tools
        return self

    def invoke(self, messages):
        self.calls.append(list(messages))
        i = 1 if self.repeat else len(self.calls)
        return AIMessage(content="", tool_calls=[{
            "id": str(i), "name": "search_academic_literature",
            "args": {"chinese_queries": [f"心理咨询方向{i}"], "english_queries": [f"counseling angle {i}"]},
        }])


class Searcher:
    def __init__(self, batches):
        self.batches = batches
        self.calls = []

    def search(self, chinese_queries, english_queries, publication_year_range=None):
        self.calls.append((chinese_queries, english_queries))
        return {"bib_pool": self.batches[min(len(self.calls) - 1, len(self.batches) - 1)], "searches": []}


class LiteratureAgentTests(unittest.TestCase):
    def test_year_range_is_locked_across_rounds_and_outside_records_removed(self):
        class WideningModel(Model):
            def invoke(self, messages):
                response = super().invoke(messages)
                response.tool_calls[0]["args"]["publication_year_range"] = {"start_year": 1900}
                return response

        class RecordingSearcher(Searcher):
            def search(self, chinese_queries, english_queries, publication_year_range=None):
                self.ranges.append(publication_year_range)
                return super().search(chinese_queries, english_queries)

        searcher = RecordingSearcher([[paper(0), {**paper(1), "year": 2019}, {**paper(2), "year": 2026}]])
        searcher.ranges = []
        model = WideningModel()
        state = create_initial_global_state(topic="心理咨询", publication_year_range={"start_year": 2020, "end_year": 2025})
        LiteratureAgent(llm=model, searcher=searcher).invoke(state)
        self.assertEqual(len(searcher.ranges), 4)
        for value in searcher.ranges:
            self.assertEqual(PublicationYearRange.model_validate(value).model_dump(), state["publication_year_range"])
        self.assertEqual([p["year"] for p in state["bib_pool"]], [2024])
        self.assertEqual(state["literature_search_report"]["publication_year_range"], state["publication_year_range"])

    def test_invalid_year_range_fails_before_model_call(self):
        model = Model()
        state = create_initial_global_state(topic="心理咨询", publication_year_range={"start_year": 2025, "end_year": 2020})
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            LiteratureAgent(llm=model).invoke(state)
        self.assertEqual(model.calls, [])
        self.assertEqual(state, before)

    def test_complete_single_tool_and_only_bib_updates(self):
        model = Model()
        records = [paper(i) for i in range(15)] + [paper(i, "en") for i in range(5)]
        agent = LiteratureAgent(llm=model, searcher=Searcher([records]))
        state = create_initial_global_state(topic="心理咨询", single_source_of_truth={"x": 1})
        before = copy.deepcopy(state)
        self.assertIs(agent.invoke(state), state)
        self.assertEqual([t.name for t in model.tools], ["search_academic_literature"])
        self.assertEqual(len(model.calls), 1)
        self.assertTrue(state["literature_search_report"]["complete"])
        for key in before:
            if key != "bib_pool":
                self.assertEqual(before[key], state[key])
        parse_literature_output(state, require_complete=True)

    def test_shortage_exhausts_four_rounds_and_returns_union(self):
        searcher = Searcher([[paper(0)], [paper(0), paper(1)], [paper(2, "en")], [paper(3)]])
        model = Model()
        state = create_initial_global_state(topic="心理咨询")
        LiteratureAgent(llm=model, searcher=searcher).invoke(state)
        report = state["literature_search_report"]
        self.assertEqual(len(searcher.calls), 4)
        self.assertEqual(report["counts"], {"zh": 3, "en": 1})
        self.assertEqual(report["shortfall"], {"zh": 12, "en": 4})
        self.assertEqual(report["stop_reason"], "round_limit")
        self.assertEqual(len(state["bib_pool"]), 4)
        self.assertIn("累计找到", model.calls[1][-1].content)

    def test_repeated_queries_are_not_reexecuted(self):
        searcher = Searcher([[paper(1)]])
        model = Model(repeat=True)
        state = create_initial_global_state(topic="心理咨询")
        LiteratureAgent(llm=model, searcher=searcher).invoke(state)
        self.assertEqual(len(model.calls), 4)
        self.assertEqual(len(searcher.calls), 1)
        self.assertEqual(len(state["bib_pool"]), 1)
        self.assertIn("error", state["literature_search_report"]["attempts"][-1])

    def test_empty_returns_diagnostic_after_limit(self):
        state = create_initial_global_state(topic="稀缺课题")
        searcher = Searcher([[]])
        LiteratureAgent(llm=Model(), searcher=searcher, max_search_rounds=3).invoke(state)
        self.assertEqual(len(searcher.calls), 3)
        self.assertEqual(state["bib_pool"], [])
        self.assertEqual(state["literature_search_report"]["shortfall"], {"zh": 15, "en": 5})

    def test_graph_can_be_embedded(self):
        agent = LiteratureAgent(llm=Model(), searcher=Searcher([[paper(1)]]))
        graph = StateGraph(PaperGlobalState)
        graph.add_node("literature", agent.graph)
        graph.add_edge(START, "literature")
        graph.add_edge("literature", END)
        result = graph.compile().invoke(create_initial_global_state(topic="心理咨询"))
        self.assertEqual(len(result["bib_pool"]), 1)
        self.assertEqual(result["literature_search_report"]["rounds"], 4)

    def test_invalid_input_preserves_state(self):
        state = create_initial_global_state()
        before = copy.deepcopy(state)
        with self.assertRaises(ValueError):
            LiteratureAgent(llm=Model()).invoke(state)
        self.assertEqual(state, before)


class LiteratureToolTests(unittest.TestCase):
    def test_formatted_reference_contains_full_bibliography(self):
        result = LiteratureRecord.model_validate({**paper(1), "authors": "张三, 李四, 王五, 赵六",
            "volume": "12", "issue": "3", "pages": "45-50", "formatted": "不得信任的旧格式"}).model_dump()
        self.assertEqual(result["formatted"],
            "张三, 李四, 王五, 等. 心理咨询研究 1[J]. Journal, 2024, 12(3): 45-50. DOI:10.1234/zh.1.")
        self.assertEqual(LiteratureRecord.model_validate(result).model_dump(), result)

    def test_formatted_reference_handles_missing_fields_and_document_types(self):
        minimal = LiteratureRecord.model_validate({**paper(1), "doi": None}).model_dump()
        self.assertEqual(minimal["formatted"], "Researcher. 心理咨询研究 1[J]. Journal, 2024.")
        conference = LiteratureRecord.model_validate({**paper(2, "en"), "document_type": "C",
            "authors": "Alice Smith, Bob Lee, Carol Wu, David Li"}).model_dump()
        self.assertIn("Alice Smith, Bob Lee, Carol Wu, et al. Counseling study 2[C]//Journal, 2024.", conference["formatted"])
        dissertation = normalize_record(self.raw(type="dissertation"), "openalex", "心理咨询")
        self.assertEqual(dissertation["document_type"], "D")
        self.assertIn("[D].", dissertation["formatted"])

    def test_year_range_validates_bounds(self):
        for value in [{"start_year": 2025, "end_year": 2020}, {"start_year": True},
                      {"start_year": "2020"}, {"end_year": 2101}, {"start_year": 1499}]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                PublicationYearRange.model_validate(value)
        self.assertTrue(PublicationYearRange(start_year=2020, end_year=2020).contains(2020))

    def test_year_range_filters_both_sources_and_checks_returned_year(self):
        for bounds, expected in [({"start_year": 2020, "end_year": 2025}, [2020, 2025]),
                                 ({"start_year": 2025}, [2025, 2026]),
                                 ({"end_year": 2020}, [2019, 2020]), (None, [2019, 2020, 2025, 2026])]:
            requests = []
            def handle(request):
                requests.append(request)
                if request.url.host == "api.openalex.org":
                    items = [self.raw(title=f"心理咨询研究 {year}", publication_year=year,
                                     doi=f"10.1234/year.{year}") for year in [2019, 2020, 2025, 2026]]
                    return httpx.Response(200, json={"results": items})
                items = [{"DOI": f"10.1234/crossref.{year}", "title": [f"心理咨询案例 {year}"],
                          "type": "journal-article", "language": "zh", "author": [{"family": "张三"}],
                          "container-title": ["研究期刊"], "published": {"date-parts": [[year]]}}
                         for year in [2019, 2020, 2025, 2026]]
                return httpx.Response(200, json={"message": {"items": items}})
            with self.subTest(bounds=bounds), httpx.Client(transport=httpx.MockTransport(handle)) as client:
                # 通过真实 StructuredTool 测试嵌套参数的 Pydantic 转换。
                result = create_literature_tool(LiteratureSearcher(client)).invoke({
                    "chinese_queries": ["心理咨询"], "english_queries": ["counseling"],
                    "publication_year_range": bounds})
                self.assertEqual(sorted(p["year"] for p in result["bib_pool"]), sorted(expected * 2))
                for request in requests:
                    filters = request.url.params.get("filter", "")
                    source = "openalex" if request.url.host == "api.openalex.org" else "crossref"
                    for value in PublicationYearRange.model_validate(bounds or {}).api_filters(source):
                        self.assertIn(value, filters)
                    if bounds is None:
                        self.assertNotIn("publication_date", filters)
                        self.assertNotIn("pub-date", filters)

    def test_irrelevant_fulltext_hits_are_rejected(self):
        self.assertFalse(matches_query("新农村农业经济管理新模式", "预约管理系统"))
        self.assertFalse(matches_query("Mental health in the general population", "online counseling"))
        self.assertTrue(matches_query("大学生心理咨询服务研究", "心理咨询"))
        self.assertTrue(matches_query("Online counseling for students", "online counseling"))

    def raw(self, **updates):
        return {"id": "https://openalex.org/W1", "title": "心理咨询研究", "type": "article",
                "language": "zh", "publication_year": 2024, "doi": "https://doi.org/10.1234/ABC",
                "authorships": [{"author": {"display_name": "张三"}}],
                "primary_location": {"source": {"display_name": "研究期刊"}}, **updates}

    def test_normalization_and_language_conflicts(self):
        result = normalize_record(self.raw(), "openalex", "心理咨询")
        self.assertEqual(result["doi"], "10.1234/abc")
        self.assertEqual(result["language_basis"], "provider")
        for changes in [{"language": "en"}, {"is_retracted": True}, {"authorships": []},
                        {"publication_year": None}, {"title": "日本語の研究"}]:
            self.assertIsNone(normalize_record(self.raw(**changes), "openalex", "心理咨询"))
        self.assertEqual(normalize_record(self.raw(language=None), "openalex", "心理咨询")["language_basis"], "title_script")

    def test_duplicate_and_quota_validation(self):
        with self.assertRaises(ValueError):
            parse_literature_output({"bib_pool": [paper(1), paper(1)]})
        with self.assertRaises(ValueError):
            parse_literature_output({"bib_pool": [paper(i) for i in range(16)]})
        self.assertEqual(parse_literature_output({"bib_pool": []}), {"bib_pool": []})

    def test_crossref_fallback_and_partial_result(self):
        calls = []
        def handle(request):
            calls.append(request)
            if request.url.host == "api.openalex.org":
                return httpx.Response(403)
            return httpx.Response(200, json={"message": {"items": [{
                "DOI": "10.1234/ABC", "title": ["心理咨询研究"], "type": "journal-article",
                "language": "zh", "author": [{"family": "张三"}], "container-title": ["研究期刊"],
                "published": {"date-parts": [[2024]]},
            }]}})
        with httpx.Client(transport=httpx.MockTransport(handle)) as client:
            result = LiteratureSearcher(client).search(["心理咨询"], ["counseling"])
        self.assertEqual(result["counts"], {"zh": 1, "en": 0})
        self.assertEqual(result["bib_pool"][0]["source"], "crossref")
        self.assertEqual(len(calls), 4)
        self.assertFalse(result["complete"])

    def test_transient_errors_retry_bounded_and_hide_key(self):
        requests = []
        def handle(request):
            requests.append(request)
            return httpx.Response(429)
        with patch("agent.literature_tool.time.sleep"), patch.dict("os.environ", {"OPENALEX_API_KEY": "secret-test-key"}), \
                httpx.Client(transport=httpx.MockTransport(handle)) as client:
            output = LiteratureSearcher(client).search(["心理咨询"], ["counseling"])
        self.assertEqual(len(requests), 12)
        self.assertEqual(output["bib_pool"], [])
        self.assertNotIn("secret-test-key", str(output))
        self.assertNotIn("secret-test-key", str(requests[0].url))


if __name__ == "__main__":
    unittest.main()
