"""大纲输出校验、全局 state 提交和无工具约束的回归测试。"""

import copy
import json
import unittest

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from agent import OutlineAgent, PaperGlobalState, create_initial_global_state


def valid_outline():
    def node(section_id, title, words=0, assets=None):
        return {"section_id": section_id, "title": title, "target_words": words,
                "status": "pending", "planned_assets": assets or []}

    return {"outline_plan": [
        node("1", "第一章 绪论"), node("1.1", "研究背景", 600),
        node("2", "第二章 相关技术"), node("2.1", "技术选型", 600),
        node("3", "第三章 系统设计"), node("3.1", "数据库设计"),
        node("3.1.1", "概念结构设计", 600, ["fig_3_1 (系统ER图)"]),
        node("3.1.2", "用户表设计", 600, ["tbl_3_1 (t_user 数据表结构三线表)"]),
    ]}


class RecordingModel:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []
        self.calls = []

    def bind(self, **kwargs):
        self.binding = kwargs
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        return AIMessage(content=self.content, tool_calls=self.tool_calls)


class OutlineAgentTests(unittest.TestCase):
    def test_success_updates_only_outline_and_passes_facts(self):
        facts = {"tech_stack": {"backend": "Spring Boot 3", "frontend": "Vue 3"}}
        state = create_initial_global_state(topic="预约系统", single_source_of_truth=facts)
        before = copy.deepcopy(state)
        model = RecordingModel(json.dumps(valid_outline()))
        agent = OutlineAgent(llm=model)
        self.assertIs(agent.invoke(state), state)
        self.assertEqual(state["outline_plan"], valid_outline()["outline_plan"])
        self.assertEqual({k: v for k, v in state.items() if k != "outline_plan"},
                         {k: v for k, v in before.items() if k != "outline_plan"})
        self.assertEqual(model.binding, {"response_format": {"type": "json_object"}})
        self.assertEqual(json.loads(model.calls[0][1].content)["single_source_of_truth"], facts)
        self.assertEqual(set(agent.graph.get_graph().nodes),
                         {"__start__", "generate_outline", "__end__"})

    def test_invalid_outputs_leave_state_unchanged(self):
        invalid = ["not json", "```json\n{}\n```", '{"outline_plan": []}']
        for change in [
            {"target_words": 0}, {"target_words": "600"}, {"target_words": True},
            {"section_id": "1.1.1.1"}, {"status": "completed"}, {"title": " "},
            {"planned_assets": [" "]}, {"extra": "正文"},
        ]:
            data = valid_outline()
            data["outline_plan"][1].update(change)
            invalid.append(json.dumps(data))
        missing = valid_outline()
        del missing["outline_plan"][1]["planned_assets"]
        invalid.append(json.dumps(missing))
        extra = valid_outline()
        extra["single_source_of_truth"] = {}
        invalid.append(json.dumps(extra))
        duplicate = valid_outline()
        duplicate["outline_plan"] *= 2
        invalid.append(json.dumps(duplicate))
        unordered = valid_outline()
        unordered["outline_plan"] = [dict(unordered["outline_plan"][0], section_id="2.1"),
                                     unordered["outline_plan"][0]]
        invalid.append(json.dumps(unordered))
        for content in invalid:
            with self.subTest(content=content):
                state = create_initial_global_state(topic="预约系统", outline_plan=valid_outline()["outline_plan"])
                before = copy.deepcopy(state)
                with self.assertRaises(ValidationError):
                    OutlineAgent(llm=RecordingModel(content)).invoke(state)
                self.assertEqual(state, before)

    def test_hierarchy_and_software_database_requirements(self):
        cases = []
        no_chapter = valid_outline()
        no_chapter["outline_plan"].pop(0)
        cases.append(no_chapter)
        no_parent = valid_outline()
        no_parent["outline_plan"].pop(5)
        cases.append(no_parent)
        no_thirds = valid_outline()
        no_thirds["outline_plan"] = no_thirds["outline_plan"][:6]
        no_thirds["outline_plan"][-1]["target_words"] = 600
        cases.append(no_thirds)
        double_count = valid_outline()
        double_count["outline_plan"][5]["target_words"] = 600
        cases.append(double_count)
        no_er = valid_outline()
        no_er["outline_plan"][6]["planned_assets"] = []
        cases.append(no_er)
        no_tables = valid_outline()
        no_tables["outline_plan"][7]["planned_assets"] = ["tbl_3_1 (测试用例)"]
        cases.append(no_tables)
        # 两项资产都放到绪论，数据库三级小节没有规划，仍应拒绝。
        wrong_location = valid_outline()
        for index in [6, 7]:
            wrong_location["outline_plan"][1]["planned_assets"] += wrong_location["outline_plan"][index]["planned_assets"]
            wrong_location["outline_plan"][index]["planned_assets"] = []
        cases.append(wrong_location)
        for data in cases:
            with self.subTest(data=data):
                state = create_initial_global_state(topic="预约系统")
                before = copy.deepcopy(state)
                with self.assertRaises(ValueError):
                    OutlineAgent(llm=RecordingModel(json.dumps(data))).invoke(state)
                self.assertEqual(state, before)

    def test_tables_from_fact_source_must_be_covered(self):
        state = create_initial_global_state(topic="预约系统", single_source_of_truth={
            "db_schemas": {"t_user": {}, "t_appointment": {}},
        })
        with self.assertRaisesRegex(ValueError, "t_appointment"):
            OutlineAgent(llm=RecordingModel(json.dumps(valid_outline()))).invoke(state)
        data = valid_outline()
        data["outline_plan"][7]["planned_assets"].append("tbl_3_2 (t_appointment 数据表结构三线表)")
        OutlineAgent(llm=RecordingModel(json.dumps(data))).invoke(state)
        self.assertEqual(state["outline_plan"], data["outline_plan"])

    def test_json_code_block_wrapper_is_normalized(self):
        raw = json.dumps(valid_outline())
        for content in ["```json\n" + raw + "\n```", "```json\n" + raw, "```\n" + raw + "\n```"]:
            with self.subTest(content=content):
                state = create_initial_global_state(topic="预约系统")
                OutlineAgent(llm=RecordingModel(content)).invoke(state)
                self.assertEqual(state["outline_plan"], valid_outline()["outline_plan"])
        for content in ["说明：\n" + raw, "```json\n" + raw[:-2], "```json\n" + raw + "\n其他说明"]:
            with self.subTest(content=content):
                with self.assertRaises(ValidationError):
                    OutlineAgent(llm=RecordingModel(content)).invoke(create_initial_global_state(topic="预约系统"))

    def test_topic_required_before_model_call(self):
        for topic in ["", " ", None]:
            model = RecordingModel(json.dumps(valid_outline()))
            with self.assertRaises(ValueError):
                OutlineAgent(llm=model).invoke({"topic": topic})
            self.assertEqual(model.calls, [])

    def test_tool_response_rejected(self):
        model = RecordingModel(json.dumps(valid_outline()),
                               [{"id": "bad", "name": "write", "args": {}}])
        state = create_initial_global_state(topic="预约系统")
        with self.assertRaises(ValueError):
            OutlineAgent(llm=model).invoke(state)
        self.assertEqual(state["outline_plan"], [])

    def test_network_failure_leaves_previous_outline(self):
        model = RecordingModel("")

        def fail(messages):
            raise RuntimeError("network unavailable")

        model.invoke = fail
        state = create_initial_global_state(topic="预约系统", outline_plan=valid_outline()["outline_plan"])
        before = copy.deepcopy(state)
        with self.assertRaises(RuntimeError):
            OutlineAgent(llm=model).invoke(state)
        self.assertEqual(state, before)

    def test_graph_can_be_composed_and_used_again(self):
        agent = OutlineAgent(llm=RecordingModel(json.dumps(valid_outline())))
        workflow = StateGraph(PaperGlobalState)
        workflow.add_node("outline", agent.graph)
        workflow.add_edge(START, "outline")
        workflow.add_edge("outline", END)
        state = create_initial_global_state(topic="预约系统")
        result = workflow.compile().invoke(state)
        self.assertEqual(result["outline_plan"], valid_outline()["outline_plan"])
        self.assertEqual(state["outline_plan"], [])
        # 无会话记忆；同一个实例可以为另一题目生成独立大纲。
        second = agent.invoke(create_initial_global_state(topic="图书管理系统"))
        self.assertEqual(second["topic"], "图书管理系统")
        self.assertNotIn("messages", second)


if __name__ == "__main__":
    unittest.main()
