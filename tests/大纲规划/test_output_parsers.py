"""解析器独立使用时的输入处理与无副作用验证。"""

import copy
import json
import unittest

from langchain_core.messages import AIMessage

from agent import create_initial_global_state
from agent.output_parsers import parse_outline_output
from test.test_outline_agent import valid_outline


class OutputParserTests(unittest.TestCase):
    def test_parse_text_and_message_without_mutating_state(self):
        raw = json.dumps(valid_outline())
        state = create_initial_global_state(topic="预约系统")
        before = copy.deepcopy(state)
        for output in [raw, AIMessage(content=raw)]:
            with self.subTest(output=type(output).__name__):
                parsed = parse_outline_output(output, state)
                self.assertEqual(parsed, valid_outline())
                self.assertEqual(state, before)
                parsed["outline_plan"][0]["title"] = "变更"
                self.assertEqual(state, before)

    def test_reject_unsupported_output_content(self):
        state = create_initial_global_state(topic="预约系统")
        for output in [None, {}, 123, AIMessage(content=[{"type": "text", "text": "{}"}])]:
            with self.subTest(output=output):
                with self.assertRaises(TypeError):
                    parse_outline_output(output, state)
                self.assertEqual(state["outline_plan"], [])


if __name__ == "__main__":
    unittest.main()
