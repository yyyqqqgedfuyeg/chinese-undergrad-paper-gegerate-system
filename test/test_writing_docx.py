"""导出集成校验：原生图表、引用、完整正文，以及真实模型配置选择。"""

import base64
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.writing.export import export_docx
from agent.writing.models import create_writing_model
from agent.writing.storage import load_table, sha256
from test.test_writing_agent import make_state


class DocxTests(unittest.TestCase):
    def test_provider_configuration_without_network(self):
        with patch.dict(os.environ, {"KIMI_API_KEY": "test-key", "KIMI_MODEL": "kimi-test",
                                     "KIMI_BASE_URL": "https://example.invalid/v1"}):
            llm = create_writing_model("KIMI")
            self.assertEqual(llm.model_name, "kimi-test")
            self.assertEqual(llm.openai_api_base, "https://example.invalid/v1")
        with self.assertRaises(ValueError):
            create_writing_model("unknown")

    def test_table_shape_rejects_missing_or_unequal_cells(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "table.json"
            for data in ({"columns": [], "rows": []}, {"columns": ["a", "b"], "rows": [["x"]]},
                         {"columns": ["a"], "rows": [[3]]}):
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    load_table(path)

    @unittest.skipUnless((Path(__file__).resolve().parents[1] / ".tools/docx/node_modules/docx").is_dir(),
                         "导出测试需要 npm install --prefix .tools/docx docx")
    def test_export_preserves_text_and_embeds_native_table_and_picture(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "writing/assets"
            assets.mkdir(parents=True)
            (assets / "source.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>')
            (assets / "figure.png").write_bytes(base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="))
            table = {"columns": ["操作", "实际结果"], "rows": [["取消", "名额释放"]]}
            for name in ("source.json", "table.json"):
                (assets / name).write_text(json.dumps(table, ensure_ascii=False), encoding="utf-8")
            state = make_state(directory, 1)
            state["outline_plan"][-1]["planned_assets"] = ["fig_3_1 (状态图)", "tbl_3_1 (验证表)"]
            content = ("系统采用统一预约状态管理，用户提交预约后由服务端校验时段与角色权限。"
                       "已经占用的时段不能重复预约，取消操作需要验证预约归属，数据库事务保证状态更新一致。"
                       "流程见[[REF_FIG:fig_3_1]]，结果见[[REF_TABLE:tbl_3_1]]。")
            relative = "writing/sections/3.1.1.md"
            (root / relative).parent.mkdir(parents=True)
            (root / relative).write_text(content, encoding="utf-8")
            state["writing_records"] = [{"section_id": "3.1.1", "title": state["outline_plan"][-1]["title"],
                "content": content, "content_path": relative, "content_sha256": sha256(content),
                "node_index": 1, "summary": "预约流程与权限。", "key_facts": ["取消释放"], "citations": [],
                "assets": [{"asset_id": "fig_3_1", "kind": "diagram", "description": "状态图",
                            "source_path": "writing/assets/source.svg", "path": "writing/assets/figure.png"},
                           {"asset_id": "tbl_3_1", "kind": "table", "description": "验证表",
                            "source_path": "writing/assets/source.json", "path": "writing/assets/table.json"}]}]
            report = export_docx(state, str(root / "output.docx"), "本文分析预约状态与资源约束。", ["预约", "约束"])
            self.assertEqual(report["figures"], 1)
            self.assertEqual(report["tables"], 1)
            self.assertTrue(report["content_complete"])
            self.assertTrue(report["native_three_line_tables"])
            self.assertNotIn("data", state["writing_records"][0]["assets"][1])


if __name__ == "__main__":
    unittest.main()
