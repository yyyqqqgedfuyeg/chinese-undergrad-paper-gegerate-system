"""少量组合场景覆盖：接力、工具 loop、校验修复、失败续跑与子图接入。"""

import copy
import json
from pathlib import Path
import tempfile
import unittest

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from agent import PaperGlobalState, Skill, WritingAgent, WritingExecutionError, create_initial_global_state
from agent.writing.tools import create_writing_tools


def make_state(root, count=4):
    outline = [{"section_id": "3", "title": "第三章 系统设计", "target_words": 0,
                "status": "pending", "planned_assets": []},
               {"section_id": "3.1", "title": "预约设计", "target_words": 0,
                "status": "pending", "planned_assets": []}]
    outline += [{"section_id": f"3.1.{i}", "title": f"设计要点{i}", "target_words": 80,
                 "status": "pending", "planned_assets": []} for i in range(1, count + 1)]
    return create_initial_global_state(topic="预约系统设计", workspace_dir=str(root),
                                       single_source_of_truth={"tech_stack": {"backend": "Spring Boot 3"}},
                                       outline_plan=outline)


class Model:
    def __init__(self, fail_after=None, tool_loop=False, bad_once=False):
        self.calls = []
        self.fail_after = fail_after
        self.tool_loop = tool_loop
        self.bad_once = bad_once

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages):
        self.calls.append(list(messages))
        context = json.loads(messages[1].content)
        if self.fail_after is not None and len(context["handoff"]) >= self.fail_after:
            raise RuntimeError("模拟服务中断")
        if self.tool_loop and not any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(content="", tool_calls=[{"name": "bash", "id": "bash_1", "args": {
                "command": "python -c \"from pathlib import Path; Path('tool-ran.txt').write_text('ok')\""}}])
        if self.bad_once and len(self.calls) == 1:
            return AIMessage(content='{"sections": []}')
        sections = [{"section_id": t["section_id"], "title": t["title"],
                     "summary": "说明预约权限与状态约束，沿用前文设计。", "key_facts": ["后端 Spring Boot 3"],
                     "content": "系统采用统一预约状态管理，用户提交预约后由服务端校验时段与角色权限。"
                                "已经占用的时段不能重复预约，取消操作需要验证预约归属，数据库事务保证状态更新一致。",
                     "assets": [], "citations": []} for t in context["current_tasks"]]
        return AIMessage(content=json.dumps({"sections": sections}, ensure_ascii=False))


class WritingTests(unittest.TestCase):
    def test_three_batches_accumulate_without_old_messages_and_embed(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Model()
            agent = WritingAgent(llm=model)
            outer = StateGraph(PaperGlobalState)
            outer.add_node("writing", agent.graph)
            outer.add_edge(START, "writing")
            outer.add_edge("writing", END)
            initial = make_state(directory, count=7)
            result = outer.compile().invoke(initial)
            self.assertEqual(initial["outline_plan"][-1]["status"], "pending")
            self.assertEqual([len(json.loads(c[1].content)["current_tasks"]) for c in model.calls], [3, 3, 1])
            self.assertEqual([len(json.loads(c[1].content)["handoff"]) for c in model.calls], [0, 3, 6])
            self.assertTrue(all(len(c) == 2 for c in model.calls))
            self.assertIn("[docx]", model.calls[0][0].content)
            self.assertTrue(all(t["status"] == "completed" for t in result["outline_plan"]))
            for record in result["writing_records"]:
                self.assertEqual((Path(directory) / record["content_path"]).read_text(), record["content"])
                self.assertTrue(record["summary"])
            self.assertNotIn("current_output", result)
            self.assertTrue(result["writing_report"]["complete"])
            # 相同输入/完成 state 再次调用不重复生成。
            self.assertIs(agent.invoke(result), result)
            self.assertEqual(len(model.calls), 3)

    def test_tool_loop_workspace_and_custom_skill(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Model(tool_loop=True)
            agent = WritingAgent(llm=model, skills=[Skill(name="fixture", description="测试技能",
                                                         instructions="保持预约术语一致。")])
            result = agent.invoke(make_state(directory, 1))
            self.assertEqual((Path(directory) / "tool-ran.txt").read_text(), "ok")
            self.assertIn("保持预约术语一致", model.calls[0][0].content)
            self.assertEqual(result["writing_report"]["tool_calls"], 1)
            self.assertIsInstance(model.calls[-1][-1], ToolMessage)
            self.assertEqual(json.loads(model.calls[-1][-1].content)["exit_code"], 0)

    def test_bounded_repair_and_reject_invalid_citation_or_missing_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            model = Model(bad_once=True)
            result = WritingAgent(llm=model).invoke(make_state(directory, 1))
            self.assertEqual(result["writing_report"]["batches"][0]["repairs"], 1)
            self.assertIsInstance(model.calls[-1][-1], HumanMessage)
        for case in ("citation", "asset", "missing_section"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                class BadModel(Model):
                    def invoke(self, messages):
                        response = super().invoke(messages)
                        data = json.loads(response.content)
                        if case == "citation":
                            data["sections"][0]["content"] += "[[REF_CITE:invented]]"
                            data["sections"][0]["citations"] = ["invented"]
                        elif case == "missing_section":
                            data["sections"] = data["sections"][:-1]
                        response.content = json.dumps(data, ensure_ascii=False)
                        return response
                state = make_state(directory)
                if case == "asset":
                    state["outline_plan"][2]["planned_assets"] = ["fig_3_1 (状态图)"]
                before = copy.deepcopy(state)
                with self.assertRaises(WritingExecutionError):
                    WritingAgent(llm=BadModel(), max_repairs=0).invoke(state)
                self.assertEqual(state, before)
                self.assertFalse((Path(directory) / "writing/manifest.json").exists())

    def test_failure_resume_and_input_or_file_change_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            state = make_state(directory)
            before = copy.deepcopy(state)
            with self.assertRaises(WritingExecutionError):
                WritingAgent(llm=Model(fail_after=3)).invoke(state)
            self.assertEqual(state, before)
            manifest = json.loads((Path(directory) / "writing/manifest.json").read_text())
            self.assertEqual(len(manifest["records"]), 3)
            self.assertFalse(manifest["report"]["complete"])
            model = Model()
            WritingAgent(llm=model).invoke(state)
            self.assertEqual(len(model.calls), 1)
            self.assertEqual(len(json.loads(model.calls[0][1].content)["handoff"]), 3)
            changed = copy.deepcopy(state)
            changed["single_source_of_truth"]["tech_stack"]["backend"] = "Django"
            with self.assertRaisesRegex(ValueError, "不同输入"):
                WritingAgent(llm=Model()).invoke(changed)
            (Path(directory) / state["writing_records"][0]["content_path"]).write_text("被修改")
            with self.assertRaisesRegex(ValueError, "缺失或被修改"):
                WritingAgent(llm=Model()).invoke(state)

    def test_no_infinite_tool_loop(self):
        class Endless(Model):
            def invoke(self, messages):
                return AIMessage(content="", tool_calls=[{"name": "not_registered", "id": "x", "args": {}}])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(WritingExecutionError, "达到上限"):
                WritingAgent(llm=Endless(), max_model_calls=2).invoke(make_state(directory, 1))
            self.assertFalse((Path(directory) / "writing/manifest.json").exists())

    def test_tools_failures_paths_and_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            tools = {t.name: t for t in create_writing_tools(directory)}
            with self.assertRaises(ValueError):
                tools["write"].invoke({"file_path": "../escape.txt", "content": "bad"})
            tools["write"].invoke({"file_path": "nested/test.txt", "content": "before"})
            tools["edit"].invoke({"file_path": "nested/test.txt", "target_content": "before", "replacement_content": "after"})
            self.assertEqual(tools["read"].invoke({"file_path": "nested/test.txt"}), "after")
            self.assertEqual(json.loads(tools["bash"].invoke({"command": "exit 7"}))["exit_code"], 7)
            result = json.loads(tools["bash"].invoke({"command": "sleep 5", "timeout_seconds": 1}))
            self.assertTrue(result["timed_out"])

    def test_invalid_outline_rejected_before_model(self):
        with tempfile.TemporaryDirectory() as directory:
            state = make_state(directory)
            state["outline_plan"][0]["target_words"] = 100
            model = Model()
            with self.assertRaises(ValueError):
                WritingAgent(llm=model).invoke(state)
            self.assertEqual(model.calls, [])


if __name__ == "__main__":
    unittest.main()
