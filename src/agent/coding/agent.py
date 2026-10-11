"""编码任务在独立工作区执行，验证后由宿主发布资产。"""
import json
from pathlib import Path
import re
import shutil
from uuid import uuid4

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from .tools import create_coding_tools
from ..security.policy import authorize, role_skill
from ..security.sandbox import scoped_path


class CodingAgent:
    role = "coding"

    def __init__(self, llm=None, max_model_calls=15):
        self.llm = llm
        self.max_model_calls = max_model_calls

    def run_asset(self, task: dict, workspace: str) -> dict:
        from ..writing.models import create_writing_model
        from ..writing.schemas import WritingAsset
        from ..writing.storage import load_table
        for key in ("section_id", "asset_id"):
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", task[key]) or task[key] in {".", ".."}:
                raise ValueError("无效编码任务标识")
        root = Path(workspace).resolve()
        run_id = uuid4().hex
        private = root / "subagents/coding" / task["section_id"] / run_id
        if private.resolve() != private:
            raise PermissionError("编码工作区路径不能经过符号链接")
        private.mkdir(parents=True)
        (private / "task.json").write_text(json.dumps(task, ensure_ascii=False, indent=2))
        tools = {t.name: t for t in create_coding_tools(private)}
        model = (self.llm or create_writing_model("KIMI")).bind_tools(list(tools.values()))
        messages = [SystemMessage(content=role_skill("coding").instructions),
                    HumanMessage(content=json.dumps(task, ensure_ascii=False))]
        trace = []
        calls = 0
        try:
            for _ in range(self.max_model_calls):
                response = model.invoke(messages)
                messages.append(response)
                if response.tool_calls:
                    for call in response.tool_calls:
                        calls += 1
                        if calls > 50:
                            raise RuntimeError("编码工具调用达到上限")
                        try:
                            authorize(self.role, call["name"])
                            result = tools[call["name"]].invoke(call["args"])
                            status = "success"
                        except Exception as exc:
                            result, status = f"{type(exc).__name__}: {exc}", "error"
                        trace.append({"tool": call["name"], "args": call["args"], "result": result})
                        messages.append(ToolMessage(content=str(result), tool_call_id=call["id"], status=status))
                    continue
                try:
                    raw = response.content.strip()
                    # 接受模型在最终 JSON 外附加说明；仍严格验证对象字段与实际文件。
                    start = raw.find("{")
                    if start < 0:
                        raise ValueError("最终答复缺少产物 JSON")
                    value, _ = json.JSONDecoder().raw_decode(raw[start:])
                    if set(value) != {"source_path", "path", "kind", "description"}:
                        raise ValueError("只返回 source_path/path/kind/description")
                    source = scoped_path(private, value["source_path"])
                    output = scoped_path(private, value["path"])
                    for path in (source, output):
                        if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
                            raise ValueError("只接受普通产物文件")
                        if not 0 < path.stat().st_size <= 20_000_000:
                            raise ValueError("产物大小无效")
                    if value["kind"] == "table":
                        data = load_table(output)
                        allowed_columns = task.get("render_constraints", {}).get("table_columns")
                        if allowed_columns is not None and len(data["columns"]) not in allowed_columns:
                            raise ValueError("表格列数没有对应模板原型")
                        extension = ".json"
                    elif value["kind"] in {"diagram", "ui"}:
                        from PIL import Image
                        with Image.open(output) as picture:
                            ratio = task.get("render_constraints", {}).get("image_aspect_ratio")
                            if ratio and abs(picture.width / picture.height / ratio - 1) > 0.01:
                                raise ValueError(f"图片宽高比须符合模板：{ratio}")
                            picture.verify()
                            if picture.format not in {"PNG", "JPEG"}:
                                raise ValueError("图片必须为 PNG/JPEG")
                            extension = ".png" if picture.format == "PNG" else ".jpg"
                    else:
                        raise ValueError("无效资产类型")
                    destination = root / "writing/assets" / task["section_id"] / task["asset_id"] / run_id
                    if destination.resolve() != destination:
                        raise PermissionError("资产发布路径不能经过符号链接")
                    destination.mkdir(parents=True)
                    shutil.copyfile(source, destination / ("source" + source.suffix))
                    shutil.copyfile(output, destination / ("output" + extension))
                    return WritingAsset(asset_id=task["asset_id"], kind=value["kind"],
                        description=value["description"],
                        source_path=str((destination / ("source" + source.suffix)).relative_to(root)),
                        path=str((destination / ("output" + extension)).relative_to(root))).model_dump()
                except (ValueError, OSError, KeyError) as exc:
                    trace.append({"validation_error": str(exc)})
                    messages.append(HumanMessage(content=f"产物验收失败，请修复：{exc}"))
            raise RuntimeError("编码达到轮次上限，未发布资产")
        finally:
            # 日志不在 subagent 可写目录内。
            log = root / "audit/coding" / f"{run_id}.json"
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
