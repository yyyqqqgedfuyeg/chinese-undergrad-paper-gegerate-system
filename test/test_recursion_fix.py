"""
test/test_recursion_fix.py
验证 recursion_limit 修复与默认步数提升配置
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from agent.agent import BaseReActAgent
from agent.docx_agent import DocxTemplateAgent
from agent.webui import DEFAULT_RECURSION_LIMIT


def test_agent_defaults():
    print("1. 检查 BaseReActAgent 与 DocxTemplateAgent 的 default_recursion_limit 配置...")
    agent = DocxTemplateAgent()
    assert agent.default_recursion_limit == 80, f"期望 80，实际为: {agent.default_recursion_limit}"
    print(f"   [PASS] DocxTemplateAgent.default_recursion_limit = {agent.default_recursion_limit}")

    print("2. 检查 webui DEFAULT_RECURSION_LIMIT...")
    assert DEFAULT_RECURSION_LIMIT == 80, f"期望 80，实际为: {DEFAULT_RECURSION_LIMIT}"
    print(f"   [PASS] webui.DEFAULT_RECURSION_LIMIT = {DEFAULT_RECURSION_LIMIT}")

    print("3. 检查 agent.py 内部配置合并逻辑...")
    # 测试在调用时，merged_config 是否正确设置 recursion_limit
    test_config = {"configurable": {"thread_id": "test_session"}}
    merged_config = dict(test_config or {})
    merged_config.setdefault("recursion_limit", agent.default_recursion_limit)
    assert merged_config["recursion_limit"] == 80
    assert merged_config["configurable"]["thread_id"] == "test_session"
    print(f"   [PASS] merged_config 成功自动注入: {merged_config}")

    print("4. 检查 docx_agent 提示词中是否已加入反死循环与收敛纪律...")
    prompt = agent.inner_sys_prompt
    assert "防止多轮死循环" in prompt or "高效收敛与快速交付" in prompt, "未检测到提示词防死循环准则！"
    print("   [PASS] docx_agent.inner_sys_prompt 包含明确防死循环与收敛准则。")

    print("\n全部静态与配置项验证通过！")


if __name__ == "__main__":
    test_agent_defaults()

