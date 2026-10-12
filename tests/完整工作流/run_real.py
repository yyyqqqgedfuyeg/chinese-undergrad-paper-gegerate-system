"""Explicit real .env workflow run, with resumable input and redacted model audit."""
import argparse
from datetime import datetime
import hashlib
import json
import re
from pathlib import Path
import sys
import time

ROOT = next(p for p in Path(__file__).resolve().parents if (p / "pyproject.toml").exists())
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from dotenv import load_dotenv
from agent import PaperWorkflow, create_initial_global_state
from agent.writing.models import create_writing_model
from agent.coding import CodingAgent


class RecordedModel:
    def __init__(self, inner, run):
        self.inner, self.run = inner, run
    def bind(self, **kwargs):
        return RecordedModel(self.inner.bind(**kwargs), self.run)
    def bind_tools(self, tools, **kwargs):
        return RecordedModel(self.inner.bind_tools(tools, **kwargs), self.run)
    def invoke(self, messages):
        start = time.monotonic()
        print("model_request " + str(messages[0].content)[:45], flush=True)
        for attempt in range(5):
            try:
                response = self.inner.invoke(messages)
                break
            except Exception as exc:
                message = re.sub(r"<ak-[^>]+>", "<account-key-id>", str(exc))
                with (self.run / "request-errors.jsonl").open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"at": datetime.now().isoformat(), "seconds": time.monotonic()-start,
                        "error_type": type(exc).__name__, "error": message}, ensure_ascii=False) + "\n")
                daily_quota = any(label in message.lower() for label in ("tpd rate limit", "daily quota", "insufficient_quota"))
                if getattr(exc, "status_code", None) != 429 or daily_quota or attempt == 4:
                    raise
                retry_after = getattr(getattr(exc, "response", None), "headers", {}).get("retry-after", "0")
                match = re.search(r"after (\d+) seconds", message)
                advertised = float(retry_after) if str(retry_after).replace(".", "", 1).isdigit() else 0
                delay = min(60, max(advertised, float(match[1]) if match else 0, 5 * 2 ** attempt))
                print(f"rate_limited: retry {attempt + 1}/4 after {delay}s", flush=True)
                time.sleep(delay)
        row = {"at": datetime.now().isoformat(), "seconds": round(time.monotonic()-start, 2),
               "model": getattr(self.inner, "model_name", getattr(getattr(self.inner, "bound", None), "model_name", None)),
               "prompt": str(messages[0].content)[:200], "content": response.content,
               "tool_calls": response.tool_calls, "usage": response.usage_metadata}
        with (self.run / "model.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"model_response seconds={row['seconds']} tools={len(response.tool_calls)} prompt={row['prompt'][:45]}", flush=True)
        return response


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--provider", choices=["KIMI", "DEEPSEEK"], default="KIMI")
    parser.add_argument("--coding-provider", choices=["KIMI", "DEEPSEEK"], help="Optional separate model profile for code generation")
    parser.add_argument("--instant", action="store_true", help="Disable thinking for supported Kimi/DeepSeek models")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=True)
    run = args.resume.resolve() if args.resume else Path(__file__).parent / "runs" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "_校园二手交易平台真实工作流")
    run.mkdir(parents=True, exist_ok=True)
    print("run_dir=" + str(run), flush=True)
    source = ROOT / "tests/模板提取/input/附件9 正文格式模板.docx"
    if args.resume:
        state = json.loads((run / "input.json").read_text())
    else:
        state = create_initial_global_state(topic="基于Spring Boot的校园二手交易平台", raw_doc_path=str(source),
            workspace_dir=str(run / "workspace"), single_source_of_truth={"tech_stack": {"backend": "Spring Boot"},
                "implementation_status": "目前仅开展论文研究方案设计，没有提供已运行系统、真实用户、访谈、交易数据或实测结果。"})
        (run / "input.json").write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tracked = [*(ROOT / "src").rglob("*.py"), *(ROOT / "skills/docx").rglob("*.py"), *(ROOT / "skills/docx").rglob("*.md")]
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
    (run / "source-hashes.json").write_text(json.dumps(hashes, indent=2))
    attempts = run / "attempts"
    attempts.mkdir(exist_ok=True)
    (attempts / (datetime.now().strftime("%Y%m%d-%H%M%S-%f") + ".json")).write_text(json.dumps({
        "config_profile": args.provider, "coding_profile": args.coding_provider, "instant": args.instant, "timeout": args.timeout,
        "source_hashes": hashes}, ensure_ascii=False, indent=2))
    started = time.monotonic()
    try:
        options = {"timeout": args.timeout, "max_retries": 0}
        if args.instant:
            options["extra_body"] = {"thinking": {"type": "disabled"}}
        inner = create_writing_model(args.provider, **options)
        print("config_profile=" + args.provider + " actual_model=" + inner.model_name, flush=True)
        model = RecordedModel(inner, run)
        coder = None
        if args.coding_provider:
            coding_model = create_writing_model(args.coding_provider, **options)
            print("coding_profile=" + args.coding_provider + " actual_model=" + coding_model.model_name, flush=True)
            coder = CodingAgent(llm=RecordedModel(coding_model, run))
        result = PaperWorkflow(llm=model, coder=coder).invoke(state)
        (run / "result.json").write_text(json.dumps({"status": "passed", "config_profile": args.provider, "actual_model": inner.model_name, "seconds": time.monotonic()-started,
            "final_doc_path": result["final_doc_path"], "workflow": result["workflow_report"],
            "coding_profile": args.coding_provider, "asset_review": result.get("asset_review_report"),
            "writing": result["writing_report"], "literature": result.get("literature_search_report"),
            "assembly": result["assembly_report"]}, ensure_ascii=False, indent=2))
        print("PASSED " + result["final_doc_path"], flush=True)
    except Exception as exc:
        message = re.sub(r"<ak-[^>]+>", "<account-key-id>", str(exc))
        (run / "result.json").write_text(json.dumps({"status": "failed", "seconds": time.monotonic()-started,
            "error_type": type(exc).__name__, "error": message}, ensure_ascii=False, indent=2))
        print("FAILED " + type(exc).__name__ + ": " + message, flush=True)
        return 1

if __name__ == "__main__":
    sys.exit(main() or 0)
