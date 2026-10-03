"""真实模型 → 11节接力 → 语义审查 → 原生图表DOCX → PDF渲染的端到端验收。

python -m test.test_writing_docx_real [--workspace 已有运行目录]
"""

import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import time

import httpx
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage

from agent import Skill, WritingAgent
from agent.writing.export import export_docx
from agent.writing.models import create_writing_model
from agent.writing.storage import atomic_write, load_table, parse_batch, sha256
from agent.writing.tools import load_project_skills
from test.writing_docx_fixture import build_state


CHECKS = ["closed_states_and_roles", "ownership_and_time_boundary", "database_invariant",
          "implementation_vs_prototype", "experimental_evidence", "cross_section_consistency", "conclusion_scope"]


def review_manuscript(llm, state, workspace):
    context = {"facts": state["single_source_of_truth"], "records": state["writing_records"]}
    prompt = """你是技术论文审校者。根据事实源、真实参考实现说明和实测证据，独立逐节审查全文。
严格检查：四种状态及合法边不漂移；本人权限与now<starts_at边界；部分唯一索引而非一般的先查后写保证资源互斥；
提交新增占用，确认维持已有占用，拒绝/取消才释放，逐句检查不能将所有审核边都说成改变占用；
固定时隙与任意重叠区间的区别；SQLite单写者与timeout不等于高并发；可信actor不等于已实现登录认证；
静态HTML不等于后端联调；20轮两个独立连接的试验只能支持有限观察；不能虚构吞吐量或稳定性保证。
检查跨节、图表说明与正文矛盾，结论是否回答了研究问题。不要仅因风格偏好报错，发现影响结论的问题必须指出。
只输出JSON：{"passed":true/false,"checks":[{"id":"规定的ID","passed":true/false,"evidence":"具体章节与判断理由"}],
"issues":[{"section_id":"编号","problem":"具体矛盾或无依据论断","required_fix":"应如何修正"}],
"abstract":"基于正文事实写300字左右中文摘要，包含问题、方法、实际结果和边界，不引文，不含标题",
"keywords":["4-5个关键词"]}。
checks必须恰好包含下列全部ID，每项必须独立判断；passed仅在所有check通过且issues为空时为true：
""" + json.dumps(CHECKS)
    result = llm.bind(response_format={"type": "json_object"}).invoke([
        SystemMessage(content=prompt), HumanMessage(content=json.dumps(context, ensure_ascii=False))])
    review = json.loads(result.content)
    atomic_write(workspace / "semantic-review.json", json.dumps(review, ensure_ascii=False, indent=2))
    assert {item["id"] for item in review["checks"]} == set(CHECKS)
    assert len(review["checks"]) == len(CHECKS)
    assert isinstance(review["abstract"], str) and len(review["abstract"]) >= 200
    assert isinstance(review["keywords"], list) and all(isinstance(v, str) for v in review["keywords"])
    return review


def repair_manuscript(llm, state, issues, workspace):
    """仅按审查问题修正文稿，保留每个标题的资产和引用约定，再复核全文。"""
    allowed = {issue["section_id"] for issue in issues}
    assert allowed <= {r["section_id"] for r in state["writing_records"]}
    messages = [
        SystemMessage(content="你负责按明确的审查问题定向修正论文。只改问题涉及的小节，不改变事实源、图表和引用key。"
                              "保留原有正确内容和必要的引用锚点，优先对原文做局部修改，删除冗余而不是扩写。"
                              "content字符数以target_words为目标，绝对不能超过target_words的2倍；英文符号也计入长度。输出JSON："
                              '{"updates":[{"section_id":"编号","content":"修正后的完整正文",'
                              '"summary":"准确摘要","key_facts":["修正后的要点"]}]}。'
                              "每个涉及的小节只返回一次，必须覆盖所有issues里的section_id。"),
        HumanMessage(content=json.dumps({"issues": issues, "facts": state["single_source_of_truth"],
                                        "tasks": [t for t in state["outline_plan"] if t["section_id"] in allowed],
                                        "records": state["writing_records"]}, ensure_ascii=False))]
    for attempt in range(3):
        response = llm.bind(response_format={"type": "json_object"}).invoke(messages)
        atomic_write(workspace / "latest-repair-output.json", response.content)
        try:
            updates = json.loads(response.content)["updates"]
            assert len(updates) == len(allowed) and {u["section_id"] for u in updates} == allowed
            by_id = {u["section_id"]: u for u in updates}
            records = []
            for record in state["writing_records"]:
                new = dict(record)
                if record["section_id"] in by_id:
                    replacement = by_id[record["section_id"]]
                    assert set(replacement) == {"section_id", "content", "summary", "key_facts"}
                    new.update(replacement)
                    new["content_sha256"] = sha256(new["content"])
                records.append(new)
            drafts = [{k: v for k, v in r.items() if k not in {"content_path", "content_sha256", "node_index"}} for r in records]
            parse_batch(json.dumps({"sections": drafts}, ensure_ascii=False),
                        [t for t in state["outline_plan"] if t["target_words"] > 0], {**state, "writing_records": []}, workspace)
            break
        except (ValueError, AssertionError, KeyError) as exc:
            if attempt == 2:
                raise
            messages.extend([response, HumanMessage(content=f"尚未提交。修正以下校验错误后返回全部updates：{exc}")])
    # 修正前保存快照，便于追踪；修正全部校验后再更新接力清单。
    versions = workspace / "review-revisions"
    versions.mkdir(exist_ok=True)
    snapshot = versions / f"revision-{len(list(versions.glob('*.json'))) + 1}.json"
    atomic_write(snapshot, json.dumps({"issues": issues, "before": state["writing_records"], "updates": updates}, ensure_ascii=False, indent=2))
    for record in records:
        if record["section_id"] in allowed:
            atomic_write(workspace / record["content_path"], record["content"])
    state["writing_records"] = records
    manifest_path = workspace / "writing/manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["records"] = records
    atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2))
    atomic_write(workspace / "completed-state.json", json.dumps(state, ensure_ascii=False, indent=2))


def run_test(workspace=None):
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env", override=True)
    workspace = Path(workspace).resolve() if workspace else root / "test/render" / datetime.now().strftime("writing-docx-%Y%m%d-%H%M%S")
    workspace.mkdir(parents=True, exist_ok=True)
    print(f"工作目录：{workspace}", flush=True)
    state = build_state(workspace)
    atomic_write(workspace / "input-state.json", json.dumps(state, ensure_ascii=False, indent=2))
    calls = []
    previous = [0.0]
    interval = float(os.getenv("WRITING_TEST_REQUEST_INTERVAL", "21"))

    def inspect(request):
        time.sleep(max(0, interval - (time.monotonic() - previous[0])))
        previous[0] = time.monotonic()
        payload = json.loads(request.content)
        trace = json.dumps(payload["messages"], ensure_ascii=False, indent=2)
        for name, value in os.environ.items():
            if name.endswith("API_KEY") and len(value) >= 8:
                trace = trace.replace(value, "[REDACTED]")
        atomic_write(workspace / "latest-model-messages.json", trace)
        context = json.loads(payload["messages"][1]["content"])
        info = {"model": payload["model"], "endpoint_host": request.url.host,
                "tasks": [t["section_id"] for t in context.get("current_tasks", [])],
                "handoff_count": len(context.get("handoff", [])), "messages": len(payload["messages"])}
        calls.append(info)
        print(f"请求 {len(calls)}：{info}", flush=True)
        last = json.loads(trace)[-1]
        if last.get("role") == "tool":
            print(f"上轮工具结果：{str(last.get('content', ''))[:300]}", flush=True)

    def response_status(response):
        print(f"HTTP {response.status_code}", flush=True)

    instructions = """本次生成一篇完整、可复核的短篇技术论文。逐项满足事实源section_requirements。
单节正文写连续、具体的论证段落，不在正文重复主标题，不用Markdown列表或代码块，不填充空话。
三个表格逐字使用canonical_table_data，不更改列名与单元格。图题description用30字以内的简短图名。
绘图建议写HTML+SVG、使用本地Chrome无头截图，中文字体Noto Sans CJK SC。
Chrome需要--no-sandbox，截图可用--headless --disable-gpu --hide-scrollbars --window-size=1200,800。
状态图要检查箭头方向、标签不交叠，四种状态各出现一次，取消边和审核拒绝边清晰分开。
页面原型必须显示“静态原型 / 模拟数据”，不得假装完成前后端联调。
handoff非空时先read至少一个与本批逻辑相关的前文章节。evidence/reference.py和evidence/evidence.json可read核验。
可一次bash同时生成多份资产；不要反复探测环境；不另写正文文件。按标识用REF_FIG/REF_TABLE引用所有本节资产。
若本批没有planned_assets，读取必要前文后直接输出正文JSON，不要调用bash计算字数、拼装JSON或生成检查脚本。
"""
    started = time.monotonic()
    with httpx.Client(event_hooks={"request": [inspect], "response": [response_status]}, timeout=300) as client:
        # 用户已确认继续使用当前指向 api.deepseek.com 的配置；不将变量名前缀冒充实际模型名。
        provider = "KIMI" if os.getenv("KIMI_API_KEY", "").strip() else "DEEPSEEK"
        llm = create_writing_model(provider, http_client=client)
        agent = WritingAgent(llm=llm, skills=load_project_skills() + [Skill(name="docx-acceptance",
                            description="完整论文验收", instructions=instructions)],
                            max_model_calls=24, max_tool_calls=60, max_repairs=3)
        agent.invoke(state)
        atomic_write(workspace / "completed-state.json", json.dumps(state, ensure_ascii=False, indent=2))
        assert len(state["writing_records"]) == 11 and state["writing_report"]["complete"]
        assert [b["handoff_count"] for b in state["writing_report"]["batches"]] == [0, 3, 6, 9]
        for record in state["writing_records"]:
            for asset in record["assets"]:
                if asset["kind"] == "table":
                    assert load_table(workspace / asset["path"]) == state["single_source_of_truth"]["canonical_table_data"][asset["asset_id"]]
        referenced = {key for r in state["writing_records"] for key in r["citations"]}
        assert referenced == {b["key"] for b in state["bib_pool"]}
        manual_issues = workspace / "manual-review-issues.json"
        manual_applied = workspace / "manual-repairs-applied.json"
        if manual_issues.exists() and not manual_applied.exists():
            issues = json.loads(manual_issues.read_text(encoding="utf-8"))
            repair_manuscript(llm, state, issues, workspace)
            atomic_write(manual_applied, json.dumps({"issues": issues, "applied": True}, ensure_ascii=False, indent=2))
        print("正文接力完成，开始独立语义审查。", flush=True)
        for review_round in range(3):
            review = review_manuscript(llm, state, workspace)
            atomic_write(workspace / f"semantic-review-{review_round + 1}.json", json.dumps(review, ensure_ascii=False, indent=2))
            if review["passed"] is True and not review["issues"] and all(c["passed"] is True for c in review["checks"]):
                break
            if review_round == 2 or not review["issues"]:
                raise AssertionError("语义审查仍有问题，见semantic-review.json")
            print(f"语义审查提出 {len(review['issues'])} 项修正，执行定向修改后重新审查。", flush=True)
            repair_manuscript(llm, state, review["issues"], workspace)
        before = len(calls)
        agent.invoke(state)
        assert len(calls) == before, "已完成任务不得重复请求模型"
    output = workspace / "output/共享设备预约系统_完整论文.docx"
    exported = export_docx(state, str(output), review["abstract"], review["keywords"])
    print(f"DOCX导出完成：{exported}", flush=True)
    profile = workspace / "libreoffice-profile"
    subprocess.run(["soffice", f"-env:UserInstallation={profile.as_uri()}", "--headless", "--convert-to", "pdf",
                    "--outdir", str(output.parent), str(output)], check=True, timeout=180, capture_output=True)
    pdf = output.with_suffix(".pdf")
    assert pdf.is_file() and pdf.stat().st_size > 10000
    subprocess.run(["pdftotext", "-layout", str(pdf), str(output.with_suffix(".txt"))], check=True)
    pdf_text = output.with_suffix(".txt").read_text(encoding="utf-8")
    assert not re.search(r"\[\[REF_|Error!|错误[!！]|Reference source not found", pdf_text, re.IGNORECASE)
    pages = pdf_text.split("\f")
    # 孤立标题、图表分页由最终页面图目检；这里只检查PDF可读与关键文本未丢失。
    assert all(record["title"] in pdf_text for record in state["writing_records"])
    preview = workspace / "preview"
    preview.mkdir(exist_ok=True)
    subprocess.run(["pdftoppm", "-scale-to", "1200", "-png", str(pdf), str(preview / "page")], check=True, timeout=180)
    report = {"result": "passed", "config_source": ".env", "model": calls[0]["model"] if calls else llm.model_name,
              "endpoint_host": calls[0]["endpoint_host"] if calls else "resume", "duration_seconds": round(time.monotonic()-started, 2),
              "requests": calls, "writing_report": state["writing_report"], "docx": exported,
              "pdf": str(pdf), "pages": len([p for p in pages if p.strip()]),
              "reference_experiment": "evidence/evidence.json", "semantic_review": "semantic-review.json",
              "visual_review": "pending_manual_inspection"}
    atomic_write(workspace / "docx-test-report.json", json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace")
    run_test(parser.parse_args().workspace)
