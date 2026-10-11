import json
from pathlib import Path
import os
import socket
import tempfile
import unittest

from agent import Skill, WritingAgent
from agent.coding.tools import create_coding_tools
from agent.security.sandbox import CodingSandbox
from agent.security.policy import authorize, ROLE_TOOLS
from agent.writing.tools import create_writing_tools


class PermissionsTests(unittest.TestCase):
    def test_writer_cannot_inject_skills_or_call_shell(self):
        from langchain_core.tools import tool
        @tool
        def arbitrary() -> str:
            """测试越权工具。"""
            return "bad"
        with self.assertRaises(PermissionError):
            WritingAgent(llm=object(), skills=[Skill("bad", "bad", tools=[arbitrary])])
        with self.assertRaises(PermissionError):
            authorize("writing", "bash")
        for role in ("outline", "literature", "template", "assembly"):
            self.assertNotIn("bash", ROLE_TOOLS[role])

    def test_writer_can_only_delegate_current_planned_asset(self):
        class Coder:
            def run_asset(self, task, workspace):
                return {"asset_id":task["asset_id"], "section_id":task["section_id"]}
        with tempfile.TemporaryDirectory() as root:
            tools = {t.name:t for t in create_writing_tools(root, tasks=[{"section_id":"1.1", "planned_assets":["fig_1 流程图"]}],
                           records=[{"section_id":"1", "content":"已验收正文"}], coder=Coder())}
            self.assertEqual(set(tools), {"read_section", "code_asset"})
            self.assertEqual(tools["read_section"].invoke({"section_id":"1"}), "已验收正文")
            with self.assertRaises(PermissionError):
                tools["read_section"].invoke({"section_id":"../../.env"})
            with self.assertRaises(PermissionError):
                tools["code_asset"].invoke({"section_id":"2", "asset_id":"fig_1", "instructions":"x"})
            self.assertEqual(json.loads(tools["code_asset"].invoke({"section_id":"1.1", "asset_id":"fig_1", "instructions":"x"}))["asset_id"], "fig_1")

    def test_coder_bash_cannot_read_host_secret_or_modify_parent(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); work = root / "work"; work.mkdir()
            secret = root / "secret.txt"; secret.write_text("host-only")
            os.environ["TEST_CODER_SECRET"] = "must-not-be-inherited"
            try:
                code = "import os,pathlib,socket; " \
                       f"assert not pathlib.Path({str(secret)!r}).exists(); " \
                       "assert 'TEST_CODER_SECRET' not in os.environ; " \
                       "pathlib.Path('/workspace/ok.txt').write_text('ok'); " \
                       "assert not pathlib.Path('/proc/1/root" + str(secret) + "').exists()"
                result = json.loads(CodingSandbox(work).run("python -c " + __import__('shlex').quote(code)))
                self.assertEqual(result["exit_code"], 0, result)
                self.assertEqual((work/"ok.txt").read_text(), "ok")
                self.assertEqual(secret.read_text(), "host-only")
                denied = json.loads(CodingSandbox(work).run("echo broken > /usr/sandbox-test"))
                self.assertNotEqual(denied["exit_code"], 0)
                with socket.socket() as server:
                    server.bind(("127.0.0.1", 0)); server.listen()
                    port = server.getsockname()[1]
                    result = json.loads(CodingSandbox(work).run(f"python -c 'import socket; socket.create_connection((\"127.0.0.1\", {port}), timeout=1)'"))
                    self.assertNotEqual(result["exit_code"], 0)
            finally:
                os.environ.pop("TEST_CODER_SECRET", None)

    def test_file_tools_reject_traversal_and_symlink(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root); work = root/"work"; work.mkdir()
            outside = root/"outside"; outside.write_text("keep")
            (work/"link").symlink_to(outside)
            tools = {t.name:t for t in create_coding_tools(work)}
            for path in ("../outside", str(outside), "link"):
                with self.assertRaises(PermissionError):
                    tools["write"].invoke({"file_path":path, "content":"bad"})
            self.assertEqual(outside.read_text(), "keep")

    def test_timeout_and_background_process_cleanup(self):
        with tempfile.TemporaryDirectory() as root:
            result = json.loads(CodingSandbox(root).run("sleep 10", 1))
            self.assertTrue(result["timed_out"])
            self.assertNotEqual(result["exit_code"], 0)

    def test_template_factory_binds_input_and_cannot_add_bash(self):
        from tests.support.paper_fixture import fixture
        from agent import DocxTemplateAgent
        from agent.coding.tools import create_coding_tools
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); state, _ = fixture(root)
            model = object()
            agent = DocxTemplateAgent(llm=model, source_path=state["new_template_path"],
                                      workspace_dir=str(root/"task"), auto_compile=False)
            tools = {t.name:t for t in agent.get_all_tools()}
            self.assertEqual(set(tools), {"inspect_template","build_template","verify_template"})
            report = tools["inspect_template"].invoke({})
            self.assertIn("paragraphs", report)
            tools["build_template"].invoke({"plan":{"edits":[]}})
            self.assertTrue(json.loads(tools["verify_template"].invoke({}))["passed"])
            with self.assertRaises(PermissionError):
                agent.register_tool(create_coding_tools(root/"coder")[0])
