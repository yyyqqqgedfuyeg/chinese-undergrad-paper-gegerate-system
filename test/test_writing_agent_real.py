"""真实 .env 验收：4 个短小节，两批接力，实际绘图、HTML 页面与 PNG 导出。

运行：.venv/bin/python -m test.test_writing_agent_real
产物保存到 test/render/writing-real-<timestamp>/，不打印模型密钥。
"""

import copy
from datetime import datetime
import json
import os
from pathlib import Path
import struct
import time

import httpx
from dotenv import load_dotenv

from agent import Skill, WritingAgent
from agent.agent import BaseReActAgent
from agent.writing.tools import load_project_skills
from test.test_writing_agent import make_state


def run_test():
    root = Path(__file__).resolve().parent.parent
    assert (root / ".env").is_file(), "缺少真实 .env"
    load_dotenv(root / ".env", override=True)
    assert os.getenv("DEEPSEEK_API_KEY", "").strip(), "缺少模型密钥"
    workspace = root / "test/render" / datetime.now().strftime("writing-real-%Y%m%d-%H%M%S")
    state = make_state(workspace)
    state["single_source_of_truth"].update({
        "tech_stack": {"backend": "Spring Boot 3", "frontend": "Vue 3", "db": "MySQL 8"},
        "roles": ["学生", "管理员"],
        "appointment_rules": ["学生提交后进入待审核状态", "管理员审核后进入已确认状态",
                              "学生可取消本人尚未开始的预约", "同一时段不能重复预约"],
        "implementation_status": "设计阶段；网页仅为原型，暂无真实实现与实测结果"})
    titles = ["预约状态流转设计", "角色与权限设计", "预约冲突处理设计", "预约页面原型设计"]
    for section, title in zip(state["outline_plan"][2:], titles):
        section.update(title=title, target_words=180)
    state["outline_plan"][2]["planned_assets"] = ["fig_3_1 (预约状态流转图，保存绘图源码并实际导出 PNG)"]
    state["outline_plan"][5]["planned_assets"] = ["fig_3_2 (预约页面原型，保存独立 HTML 并实际截图 PNG)"]
    before = copy.deepcopy(state)
    requests = []
    last_request = [0.0]
    # 当前真实服务为 3 RPM；限制请求间隔，避免工具循环触发瞬时配额。
    interval = float(os.getenv("WRITING_TEST_REQUEST_INTERVAL", "21"))

    def inspect(request):
        time.sleep(max(0, interval - (time.monotonic() - last_request[0])))
        last_request[0] = time.monotonic()
        payload = json.loads(request.content)
        names = [t["function"]["name"] for t in payload["tools"]]
        assert {"bash", "read", "write", "edit"} <= set(names)
        assert "[docx]" in payload["messages"][0]["content"]
        context = json.loads(payload["messages"][1]["content"])
        requests.append({"tasks": [t["section_id"] for t in context["current_tasks"]],
                         "handoff_count": len(context["handoff"]), "model": payload["model"],
                         "message_count": len(payload["messages"])})
        print(f"真实模型请求 #{len(requests)}：任务 {requests[-1]['tasks']}，累计前文 {len(context['handoff'])} 节，"
              f"本批消息数 {len(payload['messages'])}", flush=True)

    def inspect_response(response):
        # 只记录状态码，不将供应商错误正文中的账户标识或其他敏感信息写入报告。
        print(f"模型 HTTP 状态：{response.status_code}", flush=True)

    skills = load_project_skills() + [Skill(name="acceptance", description="短篇验收要求", instructions=(
        "本次每节180字左右，图和页面样式简洁，减少调用。图示可直接写含 SVG 的 HTML 并用现有 Chrome 无头截图，"
        "Chrome 在 root 环境需 --no-sandbox，截图使用 --headless --disable-gpu --hide-scrollbars --window-size=1000,700。"
        "所有后台进程都要退出。若 handoff 非空，必须先用 read 读取其中至少一节正文，再根据前文完成当前任务。"
        "原型必须显示“原型演示”并沿用前文角色与状态词。每个产物使用独立文件名。"))]
    started = time.monotonic()
    with httpx.Client(event_hooks={"request": [inspect], "response": [inspect_response]}, timeout=180) as client:
        base = BaseReActAgent._create_default_llm(temperature=None)
        llm = type(base)(model=base.model_name, api_key=base.openai_api_key,
                         base_url=base.openai_api_base, temperature=None, http_client=client,
                         timeout=180, max_retries=2)
        agent = WritingAgent(llm=llm, skills=skills)
        assert agent.invoke(state) is state
        assert [batch["section_ids"] for batch in state["writing_report"]["batches"]] == [
            ["3.1.1", "3.1.2", "3.1.3"], ["3.1.4"]]
        assert [batch["handoff_count"] for batch in state["writing_report"]["batches"]] == [0, 3]
        assert "bash" in state["writing_report"]["batches"][0]["tool_names"]
        assert {"bash", "read"} <= set(state["writing_report"]["batches"][1]["tool_names"])
        assert state["writing_report"]["complete"]
        assert len(state["writing_records"]) == 4
        assert all(t["status"] == "completed" for t in state["outline_plan"])
        for key in before:
            if key != "outline_plan":
                assert state[key] == before[key], f"不应修改 {key}"
        assets = []
        for record in state["writing_records"]:
            assert (workspace / record["content_path"]).read_text(encoding="utf-8") == record["content"]
            for asset in record["assets"]:
                path = workspace / asset["path"]
                data = path.read_bytes()
                assert data.startswith(b"\x89PNG\r\n\x1a\n") and b"IEND" in data[-12:]
                width, height = struct.unpack(">II", data[16:24])
                assert width >= 600 and height >= 400 and len(data) > 5000
                assert (workspace / asset["source_path"]).stat().st_size > 100
                assets.append({**asset, "width": width, "height": height, "bytes": len(data)})
        assert len(assets) == 2
        count = len(requests)
        agent.invoke(state)
        assert len(requests) == count, "续跑已完成任务不能重复调用模型"
    report = {"result": "passed", "config_source": ".env", "workspace": str(workspace),
              "duration_seconds": round(time.monotonic() - started, 2), "requests": requests,
              "assets": assets, "writing_report": state["writing_report"]}
    (workspace / "real-test-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    run_test()
