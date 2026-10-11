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

    def test_export_requires_bound_template_and_uses_assembly(self):
        from tests.support.paper_fixture import fixture, commit_fixture
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "assembly_contract"):
                export_docx(make_state(root, 1), str(root/"assembly/final.docx"), "摘要", ["关键词"])
            state, contract = fixture(root)
            commit_fixture(state)
            report = export_docx(state, str(root/"assembly/final.docx"), "原文摘要", ["预约"])
            self.assertTrue(report["template_format_preserved"])
            self.assertTrue(report["deterministic_replay_identical"])


if __name__ == "__main__":
    unittest.main()
