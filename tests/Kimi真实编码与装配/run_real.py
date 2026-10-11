"""使用 .env 的 Kimi 验证撰写→隔离编码→保格式装配；每次运行单独目录。"""
import json
from pathlib import Path
import sys
from datetime import datetime
import time
import hashlib
import shutil

ROOT = next(p for p in Path(__file__).resolve().parents if (p/"pyproject.toml").exists())
sys.path[:0] = [str(ROOT/"src"), str(ROOT)]
from dotenv import load_dotenv
load_dotenv(ROOT/".env")
from agent.writing.models import create_writing_model
from agent import WritingAgent, CodingAgent, AssemblyAgent
from tests.support.paper_fixture import fixture


class RecordedModel:
    def __init__(self, inner, path, label):
        self.inner, self.path, self.label = inner, path, label
    def bind_tools(self, tools):
        return RecordedModel(self.inner.bind_tools(tools), self.path, self.label)
    def invoke(self, messages):
        started = time.monotonic()
        response = self.inner.invoke(messages)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"role":self.label, "elapsed":time.monotonic()-started,
                "content":response.content, "tools":response.tool_calls,
                "usage":response.usage_metadata}, ensure_ascii=False)+"\n")
        print(f"{self.label}: model_response tools={len(response.tool_calls)} elapsed={time.monotonic()-started:.1f}s", flush=True)
        return response


def main():
    run = Path(__file__).parent/"runs"/(datetime.now().strftime("%Y%m%d-%H%M%S")+"_撰写委派编码并保留模板格式")
    run.mkdir(parents=True)
    print("run_dir="+str(run), flush=True)
    # 只快照实现源码，不复制环境或凭据；便于解释每轮测试对应哪版代码。
    shutil.copytree(ROOT/"src", run/"src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"))
    hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in (ROOT/"src").rglob("*.py")}
    (run/"source-hashes.json").write_text(json.dumps(hashes, ensure_ascii=False, indent=2))
    try:
        state, contract = fixture(run/"workspace")
        state["single_source_of_truth"]["workflow_steps"] = ["学生提交预约", "系统记录预约", "管理员查看预约"]
        state["single_source_of_truth"]["operations"] = {"学生": ["提交预约"], "管理员": ["查看预约"]}
        state["single_source_of_truth"]["implementation_status"] = "仅完成设计说明和静态示意图，未实现系统或进行性能测试；不包含登录、审核或取消步骤"
        state["outline_plan"][-1]["target_words"] = 240
        state["outline_plan"][-1]["planned_assets"] = [
            "tbl_1 角色权限表，恰好两列：角色、操作。学生可以提交预约，管理员可以查看预约。",
            "fig_1 学生提交预约到管理员查看预约的流程示意图，图片宽高比2:1，中文标签，不含实测性能数据。"]
        model = create_writing_model("KIMI", timeout=180)
        coder = CodingAgent(RecordedModel(model, run/"model.jsonl", "coding"), max_model_calls=12)
        writer = WritingAgent(llm=RecordedModel(model, run/"model.jsonl", "writing"), coder=coder, batch_size=1)
        result = writer.invoke(state)
        (run/"state.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
        report = AssemblyAgent(result, contract, "本文介绍预约系统的角色职责和预约流程，基于既定业务规则完成设计说明，不涉及性能测试。",
                               ["预约系统", "角色权限"], str(run/"workspace/assembly/final.docx")).invoke()
        (run/"result.json").write_text(json.dumps({"status":"passed", "provider":"KIMI", "writing":result["writing_report"], "assembly":report}, ensure_ascii=False, indent=2))
        print("真实测试通过："+str(run/"result.json"), flush=True)
    except Exception as exc:
        (run/"result.json").write_text(json.dumps({"status":"failed", "provider":"KIMI",
            "error_type":type(exc).__name__, "error":str(exc)}, ensure_ascii=False, indent=2))
        raise


if __name__ == "__main__":
    main()
