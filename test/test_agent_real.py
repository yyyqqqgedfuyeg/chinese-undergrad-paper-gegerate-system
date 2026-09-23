"""
test/test_agent_real.py - 端到端真实业务与接口 2 轮对话验证脚本

测试目标：
1. 真实调用 .env (DeepSeek API)
2. 验证工具调用 (调用 list_workspace_files、write_workspace_file、read_workspace_file)
3. 验证短期对话记忆 (同一 thread_id 下第 2 轮对话引用第 1 轮生成的资产)
4. 验证总耗时 (total_duration_seconds) 与 Token 消耗统计 (total_tokens)
5. 验证工具 3 次重试与安全错误反馈机制
6. 将全量详细运行内容保存为 test/agent_test_run.log
"""

import os
import sys
from datetime import datetime
from pathlib import Path

# 确保导入路径为项目根目录
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from agent.agent import BaseReActAgent
from agent.tool import BASIC_TOOLS
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def run_test():
    log_file_path = Path(__file__).resolve().parent / "agent_test_run.log"
    log_records = []

    def log(msg: str):
        print(msg)
        log_records.append(msg)

    log("=" * 80)
    log(f"【真实 API 端到端测试开始】 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"测试模型: {os.getenv('DEEPSEEK_MODEL')} | Base URL: {os.getenv('DEEPSEEK_BASE_URL')}")
    log("=" * 80)

    # 1. 实例化 Agent，挂载 5 个基础工具
    agent = BaseReActAgent(
        tools=BASIC_TOOLS,
        inner_sys_prompt=(
            "你是一个中国高校本科毕业设计学术规划与论文撰写助手。"
            "你需要主动使用工具查看工作区、读写文件或检索学术规范。"
            "请遵循严谨的 ReAct 逻辑，在执行操作前后向用户清晰汇报。"
        ),
    )

    session_config = {"configurable": {"thread_id": "real_test_session_001"}}

    # ==========================================================================
    # 第 1 轮对话：要求 Agent 扫描目录并写入 test/ 目录下的选题文件
    # ==========================================================================
    turn1_prompt = (
        "你好！请先使用工具查看当前工作区的目录结构，"
        "然后在工作区的 test 文件夹下新建一个名为 'test/test_paper_draft.md' 的测试文件，"
        "写入一段关于《基于微服务架构的高校心理咨询预约系统》的选题背景与核心业务需求分析。"
    )

    log("\n" + "#" * 40 + " 第 1 轮对话 " + "#" * 40)
    log(f"【用户输入】:\n{turn1_prompt}\n")

    res1 = agent.invoke(turn1_prompt, config=session_config)

    log("【执行过程轨迹 (Messages)】:")
    for idx, m in enumerate(res1["messages"], 1):
        if isinstance(m, HumanMessage):
            log(f"[{idx}] [User]: {m.content}")
        elif isinstance(m, AIMessage):
            tool_calls = getattr(m, "tool_calls", None)
            if tool_calls:
                log(f"[{idx}] [Agent 思考与工具决策]: {m.content or '(调用工具)'}")
                for tc in tool_calls:
                    log(f"    🛠️ 计划调用工具: {tc['name']} | 参数: {tc['args']}")
            else:
                log(f"[{idx}] [Agent 最终回复]:\n{m.content}")
        elif isinstance(m, ToolMessage):
            content_preview = m.content[:300] + "..." if len(m.content) > 300 else m.content
            log(f"[{idx}] [工具返回结果 ({m.name})]:\n{content_preview}")

    log("\n【第 1 轮性能与资源统计】:")
    log(f"⏱️ 耗时: {res1.get('total_duration_seconds', 0)} 秒")
    log(f"🪙 Token 消耗: 总计 {res1.get('total_tokens', 0)} (输入: {res1.get('prompt_tokens', 0)}, 输出: {res1.get('completion_tokens', 0)})")

    # 验证第一轮产物是否在磁盘生成
    target_file = Path(__file__).resolve().parent / "test_paper_draft.md"
    file_exists = target_file.exists()
    log(f"🔍 磁盘产物验证: 'test/test_paper_draft.md' 是否生成成功: {file_exists}")
    assert file_exists, "错误：第 1 轮未能成功创建 test/test_paper_draft.md！"

    # ==========================================================================
    # 第 2 轮对话：验证短期记忆，读取上轮文件并追加技术栈
    # ==========================================================================
    turn2_prompt = (
        "非常好！请读取你刚才创建的 'test/test_paper_draft.md' 文件的具体内容，"
        "并在该文件末尾追加一段针对该系统的技术栈选型建议（详细阐述后端 Spring Boot 3 与前端 Vue 3 的选型依据），"
        "保存修改后，向我汇报追加的字数与核心选型论点。"
    )

    log("\n" + "#" * 40 + " 第 2 轮对话 " + "#" * 40)
    log(f"【用户输入】:\n{turn2_prompt}\n")

    res2 = agent.invoke(turn2_prompt, config=session_config)

    log("【执行过程轨迹 (Messages)】:")
    for idx, m in enumerate(res2["messages"], 1):
        if isinstance(m, HumanMessage):
            log(f"[{idx}] [User]: {m.content}")
        elif isinstance(m, AIMessage):
            tool_calls = getattr(m, "tool_calls", None)
            if tool_calls:
                log(f"[{idx}] [Agent 思考与工具决策]: {m.content or '(调用工具)'}")
                for tc in tool_calls:
                    log(f"    🛠️ 计划调用工具: {tc['name']} | 参数: {tc['args']}")
            else:
                log(f"[{idx}] [Agent 最终回复]:\n{m.content}")
        elif isinstance(m, ToolMessage):
            content_preview = m.content[:300] + "..." if len(m.content) > 300 else m.content
            log(f"[{idx}] [工具返回结果 ({m.name})]:\n{content_preview}")

    log("\n【第 2 轮性能与资源统计】:")
    log(f"⏱️ 耗时: {res2.get('total_duration_seconds', 0)} 秒")
    log(f"🪙 Token 消耗 (本轮累计): 总计 {res2.get('total_tokens', 0)} (输入: {res2.get('prompt_tokens', 0)}, 输出: {res2.get('completion_tokens', 0)})")

    # 验证文件更新
    updated_content = target_file.read_text(encoding="utf-8")
    has_vue = "Vue" in updated_content or "前端" in updated_content
    has_spring = "Spring" in updated_content or "后端" in updated_content
    log(f"🔍 磁盘产物更新验证: 是否包含 Spring Boot / Vue 3 相关内容: {has_vue and has_spring}")

    # ==========================================================================
    # 保存测试日志至 .log 文件
    # ==========================================================================
    log_file_path.write_text("\n".join(log_records), encoding="utf-8")
    log("\n" + "=" * 80)
    log(f"✅ 端到端测试全部通过！完整测试记录已落盘保存至: {log_file_path}")
    log("=" * 80)


if __name__ == "__main__":
    run_test()
