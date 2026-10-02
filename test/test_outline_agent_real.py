"""手动运行：python -m test.test_outline_agent_real（使用根目录真实 .env）。"""

import copy
import json
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv

from agent import OutlineAgent, create_initial_global_state
from agent.agent import BaseReActAgent
from agent.output_parsers import OutlineOutput


def run_test():
    root = Path(__file__).resolve().parent.parent
    env_path = root / ".env"
    assert env_path.is_file(), "项目根目录缺少真实 .env"
    load_dotenv(env_path, override=True)
    assert os.getenv("DEEPSEEK_API_KEY", "").strip(), ".env 中缺少真实 API Key"
    request_count = 0

    def inspect_request(request):
        nonlocal request_count
        payload = json.loads(request.content)
        assert "tools" not in payload and "functions" not in payload, "模型请求不允许携带工具"
        assert payload["response_format"] == {"type": "json_object"}
        request_count += 1

    def record_response(response):
        response.read()
        if response.is_success:
            data = response.json()
            message = data.get("choices", [{}])[0].get("message", {})
            (root / "test" / "outline_agent_response.log").write_text(
                message.get("content") or "", encoding="utf-8",
            )

    state = create_initial_global_state(
        topic="基于 Spring Boot 和 Vue 的高校心理咨询预约系统的设计与实现",
        single_source_of_truth={
            "tech_stack": {"backend": "Spring Boot 3", "frontend": "Vue 3", "db": "MySQL 8.0"},
            "functional_modules": ["用户认证", "心理咨询预约", "咨询记录管理"],
            "db_schemas": {
                "t_user": {"pk": "id", "fields": ["id", "username", "password_hash", "role"]},
                "t_appointment": {"pk": "id", "fields": ["id", "user_id", "counselor_id", "status"]},
                "t_record": {"pk": "id", "fields": ["id", "appointment_id", "content"]},
            },
            "experiment_methods": "功能测试与系统压力测试",
        },
    )
    before = copy.deepcopy(state)
    with httpx.Client(event_hooks={"request": [inspect_request], "response": [record_response]}, timeout=180) as client:
        llm = BaseReActAgent._create_default_llm(temperature=None)
        # 保留 .env 的模型、密钥和服务地址，仅注入请求检查及超时。
        llm = type(llm)(model=llm.model_name, api_key=llm.openai_api_key,
                       base_url=llm.openai_api_base, temperature=None,
                       http_client=client, timeout=180, max_retries=0)
        agent = OutlineAgent(llm=llm)
        assert agent.invoke(state) is state

    OutlineOutput.model_validate({"outline_plan": state["outline_plan"]})
    assert request_count == 1, "应一次真实模型调用完成大纲生成"
    for key in before:
        if key != "outline_plan":
            assert state[key] == before[key], f"不应修改 {key}"
    assert any(section["planned_assets"] for section in state["outline_plan"]), "应包含图表规划"
    assert state["outline_plan"][0]["section_id"] == "1"
    assert "第一章" in state["outline_plan"][0]["title"]
    assert any(section["section_id"].count(".") == 2 for section in state["outline_plan"])
    assets = [asset for section in state["outline_plan"] for asset in section["planned_assets"]]
    for table_name in state["single_source_of_truth"]["db_schemas"]:
        assert any(table_name in asset for asset in assets), f"缺少 {table_name} 数据表"
    assert len({section["section_id"].split('.')[0] for section in state["outline_plan"]}) >= 6
    report = {
        "result": "passed", "config_source": ".env", "model": llm.model_name,
        "real_requests": request_count, "tools_sent": False,
        "section_count": len(state["outline_plan"]),
        "heading_counts": {str(level): sum(section["section_id"].count(".") == level - 1
                                          for section in state["outline_plan"]) for level in [1, 2, 3]},
        "database_assets": [asset for asset in assets if "ER" in asset or "数据表" in asset or "表结构" in asset],
        "global_state": state,
    }
    log_path = root / "test" / "outline_agent_real.log"
    log_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"真实 .env 测试通过：标题层级数量 {report['heading_counts']}，"
          f"{request_count} 次模型调用，无工具，已更新全局 state。记录：{log_path}")


if __name__ == "__main__":
    run_test()
