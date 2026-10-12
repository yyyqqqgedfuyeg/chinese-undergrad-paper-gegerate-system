"""顺序批次接力：prepare → write_batch → commit_batch → 下一批 / END。"""

import copy
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from ..agent import Skill
from ..security.policy import authorize, reject_extra_tools
from ..state import PaperGlobalState
from .prompts import WRITING_PROMPT
from .models import create_writing_model
from .schemas import BatchOutput, WritingRecord, handoff_context
from .storage import (asset_id, atomic_write, input_fingerprint, parse_batch, sha256,
                      validate_records)
from .tools import create_writing_tools, load_project_skills


class WritingState(PaperGlobalState, total=False):
    writing_tasks: list[dict[str, Any]]
    current_output: dict[str, Any] | None
    batch_metrics: dict[str, Any]


class WritingExecutionError(RuntimeError):
    """当前批次失败；已提交批次保存在 manifest，可用原始输入续跑。"""


class WritingAgent:
    """每批最多三个叶子标题，批内和批间均顺序执行，不继承模型对话历史。

    invoke 成功后原地更新 state。异常时不提交失败批次，已成功批次可从
    workspace_dir/writing/manifest.json 恢复。相同工作目录不支持并发运行。
    """

    state_schema = PaperGlobalState

    def __init__(self, llm=None, skills: list[Skill] | None = None, batch_size: int = 3,
                 max_model_calls: int = 12, max_tool_calls: int = 30, max_repairs: int = 2, coder=None):
        for name, value, low, high in (("batch_size", batch_size, 1, 3),
                                      ("max_model_calls", max_model_calls, 1, 100),
                                      ("max_tool_calls", max_tool_calls, 1, 200),
                                      ("max_repairs", max_repairs, 0, 5)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError(f"{name} 必须为 {low}-{high} 的整数")
        self.llm = llm if llm is not None else create_writing_model()
        self.skills = load_project_skills() if skills is None else list(skills)
        reject_extra_tools(self.skills)
        self.coder = coder
        self.batch_size = batch_size
        self.max_model_calls = max_model_calls
        self.max_tool_calls = max_tool_calls
        self.max_repairs = max_repairs
        workflow = StateGraph(WritingState, input_schema=PaperGlobalState, output_schema=PaperGlobalState)
        workflow.add_node("prepare", self._prepare)
        workflow.add_node("write_batch", self._write_batch)
        workflow.add_node("commit_batch", self._commit_batch)
        workflow.add_edge(START, "prepare")
        workflow.add_conditional_edges("prepare", self._next, {"write": "write_batch", "end": END})
        workflow.add_edge("write_batch", "commit_batch")
        workflow.add_conditional_edges("commit_batch", self._next, {"write": "write_batch", "end": END})
        self.graph = workflow.compile()

    def get_skills(self):
        return list(self.skills)

    def get_all_tools(self, workspace_dir: str, *, tasks=(), records=(), facts=None, issued=None, constraints=None, prepared_instructions=None):
        reject_extra_tools(self.skills)
        return create_writing_tools(workspace_dir, tasks=tasks, records=records,
                                    coder=self.coder, facts=facts, issued=issued, constraints=constraints,
                                    prepared_instructions=prepared_instructions)

    @staticmethod
    def _tasks(state):
        if not isinstance(state.get("topic"), str) or not state["topic"].strip():
            raise ValueError("撰写需要非空 topic")
        if not isinstance(state.get("workspace_dir"), str) or not state["workspace_dir"].strip():
            raise ValueError("撰写需要 workspace_dir")
        outline = state.get("outline_plan", [])
        if not isinstance(outline, list) or not outline:
            raise ValueError("撰写需要非空 outline_plan")
        ids, numbers = [], []
        for item in outline:
            sid = item.get("section_id", "")
            if not isinstance(sid, str) or not re.fullmatch(r"[1-9]\d*(?:\.[1-9]\d*){0,2}", sid):
                raise ValueError("无效 section_id")
            if sid in ids or ("." in sid and sid.rsplit(".", 1)[0] not in ids):
                raise ValueError("大纲存在重复标题或缺少前置父标题")
            if not isinstance(item.get("title"), str) or not item["title"].strip():
                raise ValueError("标题不能为空")
            if type(item.get("target_words")) is not int or item["target_words"] < 0:
                raise ValueError("target_words 必须为非负整数")
            if item.get("status") not in {"pending", "in_progress", "completed"}:
                raise ValueError("无效的标题状态")
            if not isinstance(item.get("planned_assets"), list) or any(
                    not isinstance(a, str) for a in item["planned_assets"]):
                raise ValueError("planned_assets 必须为字符串列表")
            ids.append(sid)
            numbers.append(tuple(map(int, sid.split("."))))
        if numbers != sorted(numbers):
            raise ValueError("大纲必须按章节数字先序排列")
        tasks, assets = [], set()
        for item in outline:
            parent = any(sid.startswith(item["section_id"] + ".") for sid in ids)
            if parent:
                if item["target_words"] or item["planned_assets"]:
                    raise ValueError("父标题不能分配正文或资产任务，请分配到叶子标题")
            else:
                if item["target_words"] <= 0:
                    raise ValueError("叶子标题必须有正整数字数")
                for planned in item["planned_assets"]:
                    key = asset_id(planned)
                    if key in assets:
                        raise ValueError("planned_assets 中存在重复标识")
                    assets.add(key)
                tasks.append(copy.deepcopy(item))
        return tasks

    def _prepare(self, state):
        if state.get("research_lock"):
            from ..research import assert_research_lock
            assert_research_lock(state)
        tasks = self._tasks(state)
        root = Path(state["workspace_dir"]).resolve()
        root.mkdir(parents=True, exist_ok=True)
        manifest_path = root / "writing" / "manifest.json"
        records = state.get("writing_records", [])
        report = {"complete": False, "completed_sections": 0, "total_sections": len(tasks),
                  "batches": [], "model_calls": 0, "tool_calls": 0, "total_tokens": 0,
                  "duration_seconds": 0.0}
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("version") != 1 or manifest.get("input_fingerprint") != input_fingerprint(state):
                raise ValueError("工作目录已有不同输入的撰写记录；请使用新工作目录")
            records = manifest["records"]
            report = manifest["report"]
        records = validate_records(root, records, tasks, state)
        if not records and any(t["status"] == "completed" for t in tasks):
            raise ValueError("存在 completed 小节但缺少可验证的接力记录，不能静默跳过")
        report = {**report, "complete": len(records) == len(tasks),
                  "completed_sections": len(records), "total_sections": len(tasks)}
        return {"writing_tasks": tasks, "writing_records": records,
                "writing_manifest_path": str(manifest_path), "writing_report": report,
                "outline_plan": self._updated_outline(state["outline_plan"], records),
                "current_output": None, "batch_metrics": {}}

    @staticmethod
    def _updated_outline(outline, records):
        completed = {record["section_id"] for record in records}
        updated = copy.deepcopy(outline)
        for item in reversed(updated):
            sid = item["section_id"]
            if item["target_words"] > 0:
                item["status"] = "completed" if sid in completed else "pending"
            else:
                leaves = [x for x in updated if x["target_words"] > 0 and x["section_id"].startswith(sid + ".")]
                done = sum(x["section_id"] in completed for x in leaves)
                item["status"] = "completed" if done == len(leaves) else "in_progress" if done else "pending"
        return updated

    @staticmethod
    def _next(state):
        return "write" if len(state["writing_records"]) < len(state["writing_tasks"]) else "end"

    def _write_batch(self, state):
        root = Path(state["workspace_dir"]).resolve()
        records = state["writing_records"]
        tasks = state["writing_tasks"][len(records):len(records) + self.batch_size]
        # 图表密集章节预留正文生成和一致性修复预算；仍按连续叶子标题推进。
        while len(tasks) > 1 and sum(len(t["planned_assets"]) for t in tasks) > 4:
            tasks = tasks[:-1]
        from ..assembly.engine import asset_constraints
        from .prepared_assets import load_prepared, save_prepared
        constraints = asset_constraints(state)
        issued, prepared_instructions = load_prepared(root, state, tasks, constraints)
        error_path = root / "writing/last-batch-error.json"
        batch_identity = {"input_fingerprint": input_fingerprint(state),
                          "section_ids": [t["section_id"] for t in tasks]}
        previous_errors = []
        if error_path.exists():
            saved_error = json.loads(error_path.read_text())
            if all(saved_error.get(k) == v for k, v in batch_identity.items()):
                previous_errors = saved_error.get("errors", [])
        tools = {tool.name: tool for tool in self.get_all_tools(str(root), tasks=tasks, records=records,
                    facts=state.get("single_source_of_truth", {}), issued=issued,
                    constraints=constraints, prepared_instructions=prepared_instructions)}
        if len(records) <= 3:
            tools.pop("read_section", None)
        if not any(task["planned_assets"] for task in tasks):
            tools.pop("code_asset", None)
        asset_tool = tools.get("code_asset")
        from .storage import asset_id
        planned_keys = {(t["section_id"], asset_id(a)) for t in tasks for a in t["planned_assets"]}
        asset_repair_pending = any(any(label in error for label in ("审查", "图表", "资产"))
                                   for error in previous_errors)
        model = self.llm.bind_tools(list(tools.values())) if tools else self.llm
        prompt = WRITING_PROMPT
        prompt += "\n已挂载项目技能:\n" + "\n".join(
            f"[{skill.name}] {skill.description}\n{skill.instructions}" for skill in self.skills)
        prompt += "\n最终输出 JSON Schema:\n" + json.dumps(BatchOutput.model_json_schema(), ensure_ascii=False)
        context = {"topic": state["topic"], "single_source_of_truth": state.get("single_source_of_truth", {}),
                   "bib_pool": state.get("bib_pool", []),
                   "outline": [{"section_id": t["section_id"], "title": t["title"]} for t in state["outline_plan"]],
                   "current_tasks": tasks,
                   "asset_render_constraints": constraints,
                   "previous_validation_errors": previous_errors,
                   "prepared_assets": [{"section_id": key[0], "asset": asset,
                                        "instructions": prepared_instructions[key]} for key, asset in issued.items()],
                   "length_constraints": [{"section_id": t["section_id"], "target_characters": t["target_words"],
                        "minimum_characters": max(1, int(t["target_words"] * 0.6)), "maximum_characters": t["target_words"] * 2} for t in tasks],
                   "handoff": handoff_context(records),
                   "recent_sections": [{"section_id": r["section_id"], "title": r["title"], "content": r["content"]} for r in records[-3:]],
                   "previous_tail": records[-1]["content"][-500:] if records else ""}
        messages = [SystemMessage(content=prompt), HumanMessage(content=json.dumps(context, ensure_ascii=False))]
        metrics = {"node_index": max((r["node_index"] for r in records), default=0) + 1,
                   "section_ids": [t["section_id"] for t in tasks], "handoff_count": len(records),
                   "model_calls": 0, "tool_calls": 0, "tool_names": [], "total_tokens": 0}
        started = time.monotonic()
        repairs = 0
        try:
            for _ in range(self.max_model_calls):
                if metrics["model_calls"] >= self.max_model_calls:
                    break
                if "code_asset" in tools and planned_keys <= issued.keys() and not asset_repair_pending:
                    tools.pop("code_asset")
                    model = self.llm.bind_tools(list(tools.values())) if tools else self.llm
                    messages.append(HumanMessage(content="本批规划资产已全部生成。现在输出完整正文 JSON，使用已返回的资产元数据；提交前会统一审查实际图片和事实，发现问题后才重新开放修复工具。"))
                if "read_section" in tools and metrics["tool_names"].count("read_section") >= 2:
                    tools.pop("read_section")
                    model = self.llm.bind_tools(list(tools.values())) if tools else self.llm
                    messages.append(HumanMessage(content="前文读取预算已用完。请依据已提供的研究事实、章节摘要和正文完成当前批次；仅在有规划资产时调用 code_asset。"))
                response = model.invoke(messages)
                metrics["model_calls"] += 1
                metrics["total_tokens"] += (getattr(response, "usage_metadata", None) or {}).get("total_tokens", 0)
                messages.append(response)
                if response.tool_calls:
                    for call in response.tool_calls:
                        if metrics["tool_calls"] >= self.max_tool_calls:
                            raise ValueError("本批工具调用达到上限")
                        metrics["tool_calls"] += 1
                        metrics["tool_names"].append(call["name"])
                        try:
                            authorize("writing", call["name"])
                            if call["name"] not in tools:
                                raise ValueError("未注册工具")
                            result = tools[call["name"]].invoke(call["args"])
                            if call["name"] == "code_asset":
                                save_prepared(root, state, constraints, issued, prepared_instructions)
                                asset_repair_pending = False
                            tool_message = ToolMessage(content=str(result), tool_call_id=call["id"])
                        except Exception as exc:
                            status_code = getattr(exc, "status_code", None)
                            if status_code in {401, 402, 403, 429} or (
                                    isinstance(status_code, int) and status_code >= 500):
                                # Provider failures cannot be fixed by rewriting tool instructions.
                                raise
                            tool_message = ToolMessage(content=f"工具失败: {type(exc).__name__}: {exc}",
                                                       tool_call_id=call["id"], status="error")
                        messages.append(tool_message)
                    continue
                try:
                    output = parse_batch(response.content, tasks, state, root)
                    for section in output.sections:
                        for asset in section.assets:
                            approved = issued.get((section.section_id, asset.asset_id))
                            if approved is None or any(approved[k] != getattr(asset, k)
                                    for k in ("asset_id", "kind", "path", "source_path")):
                                raise ValueError("资产标识、类型和路径必须来自本批 code_asset 验收结果")
                    if state.get("research_lock"):
                        from ..research import review_consistency
                        asset_data = []
                        images = []
                        for section in output.sections:
                            for asset in section.assets:
                                asset_data.append({"asset_id": asset.asset_id,
                                    "source": (root / asset.source_path).read_text(encoding="utf-8"),
                                    "table": (root / asset.path).read_text(encoding="utf-8") if asset.kind == "table" else None})
                                if asset.kind != "table":
                                    images.append({"asset_id": asset.asset_id, "path": str(root / asset.path)})
                        if metrics["model_calls"] >= self.max_model_calls:
                            raise ValueError("本批模型调用预算不足以进行一致性审查")
                        metrics["model_calls"] += 1
                        metrics["consistency_review"] = review_consistency(self.llm, state,
                            {"sections": output.model_dump(), "asset_data": asset_data}, images=images)
                except (ValueError, TypeError, AttributeError, OSError) as exc:
                    previous_errors = (previous_errors + [str(exc)])[-3:]
                    atomic_write(error_path, json.dumps({**batch_identity, "errors": previous_errors},
                                                       ensure_ascii=False, indent=2))
                    if repairs >= self.max_repairs:
                        raise ValueError(f"本批输出校验失败: {exc}") from exc
                    repairs += 1
                    if asset_tool is not None:
                        tools["code_asset"] = asset_tool
                        asset_repair_pending = True
                        model = self.llm.bind_tools(list(tools.values()))
                    messages.append(HumanMessage(content=f"本批尚未提交。请修正以下错误并重新输出完整 JSON；"
                        f"已有有效资产可复用：{str(exc)[:2000]}"
                        "若为长度错误：直接改写到 target_characters 附近，不要贴近 maximum_characters；"
                        "删除重复的英文类名、完整字段枚举和图表中已有细节，不要只删几个字后重复提交。"))
                    continue
                metrics["duration_seconds"] = round(time.monotonic() - started, 3)
                metrics["repairs"] = repairs
                return {"current_output": output.model_dump(), "batch_metrics": metrics}
            raise ValueError("本批模型调用达到上限，未获得有效正文")
        except Exception as exc:
            raise WritingExecutionError(
                f"撰写批次 {metrics['section_ids']} 失败；已提交 {len(records)} 节。"
                f"可用相同输入续跑，记录位置: {root / 'writing' / 'manifest.json'}。原因: {exc}") from exc

    def _commit_batch(self, state):
        root = Path(state["workspace_dir"]).resolve()
        previous = state["writing_records"]
        # 工具可写文件，提交前再次确认前文未被意外修改。
        validate_records(root, previous, state["writing_tasks"], state)
        records = list(previous)
        for section in state["current_output"]["sections"]:
            relative = f"writing/sections/{section['section_id']}.md"
            record = WritingRecord(**section, content_path=relative, content_sha256=sha256(section["content"]),
                                   node_index=state["batch_metrics"]["node_index"],
                                   asset_sha256={value: hashlib.sha256((root/value).read_bytes()).hexdigest()
                                       for a in section["assets"] for value in (a["path"], a["source_path"])})
            atomic_write(root / relative, record.content)
            records.append(record.model_dump())
        metrics = state["batch_metrics"]
        report = {**state["writing_report"], "completed_sections": len(records),
                  "complete": len(records) == len(state["writing_tasks"]),
                  "batches": state["writing_report"]["batches"] + [metrics]}
        for name in ("model_calls", "tool_calls", "total_tokens", "duration_seconds"):
            report[name] = round(report[name] + metrics[name], 3)
        manifest = {"version": 1, "input_fingerprint": input_fingerprint(state),
                    "records": records, "report": report}
        atomic_write(root / "writing" / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return {"writing_records": records, "writing_report": report,
                "outline_plan": self._updated_outline(state["outline_plan"], records),
                "current_output": None, "batch_metrics": {}}

    def invoke(self, state: PaperGlobalState, config=None) -> PaperGlobalState:
        tasks = self._tasks(state)
        options = dict(config or {})
        # 图表密集时批次可缩至一节；上限必须覆盖完整任务的最坏批次数。
        options.setdefault("recursion_limit", 4 + 2 * len(tasks))
        result = self.graph.invoke(copy.deepcopy(state), config=options)
        for key in ("outline_plan", "writing_records", "writing_report", "writing_manifest_path"):
            state[key] = result[key]
        return state


SequentialWritingAgent = WritingAgent
