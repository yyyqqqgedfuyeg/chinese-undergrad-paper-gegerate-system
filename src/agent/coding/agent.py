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

    def __init__(self, llm=None, max_model_calls=24):
        self.llm = llm
        self.max_model_calls = max_model_calls
        self.runtime_profile = None

    def run_asset(self, task: dict, workspace: str) -> dict:
        from ..writing.models import create_writing_model
        from ..writing.schemas import WritingAsset
        from ..writing.storage import load_table
        for key in ("section_id", "asset_id"):
            if not re.fullmatch(r"[A-Za-z0-9_.-]+", task[key]) or task[key] in {".", ".."}:
                raise ValueError("无效编码任务标识")
        task = dict(task)
        prior_source = task.pop("previous_source_path", None)
        previous_text = None
        root = Path(workspace).resolve()
        run_id = uuid4().hex
        private = root / "subagents/coding" / task["section_id"] / run_id
        if private.resolve() != private:
            raise PermissionError("编码工作区路径不能经过符号链接")
        private.mkdir(parents=True)
        if prior_source:
            previous = scoped_path(root, prior_source)
            if not previous.is_file() or previous.stat().st_size > 20_000_000:
                raise ValueError("无效的待修复源码")
            source_text = previous.read_text(encoding="utf-8")
            previous_text = source_text
            seeded = private / ("previous_source" + previous.suffix)
            seeded.write_text(source_text, encoding="utf-8")
            task["previous_source"] = seeded.name
        (private / "task.json").write_text(json.dumps(task, ensure_ascii=False, indent=2))
        tools = {t.name: t for t in create_coding_tools(private)}
        base_model = self.llm or create_writing_model("KIMI")
        model = base_model.bind_tools(list(tools.values()))
        final_model = base_model.bind(response_format={"type": "json_object"}) if hasattr(base_model, "bind") else base_model
        trace = []
        calls = 0
        try:
            if self.runtime_profile is None:
                probe = tools["bash"].invoke({"command": """python - <<'PY'
import importlib.util, json, shutil, subprocess, sys
fonts = subprocess.run(['fc-list', ':lang=zh', '--format=%{file}\\n'], capture_output=True, text=True) if shutil.which('fc-list') else None
print(json.dumps({'python': sys.executable,
    'modules': {name: importlib.util.find_spec(name) is not None for name in ['PIL', 'matplotlib', 'numpy', 'playwright']},
    'commands': {name: shutil.which(name) for name in ['dot', 'plantuml', 'java', 'chromium']},
    'chinese_fonts': sorted(set(fonts.stdout.splitlines()))[:12] if fonts else []}))
PY"""})
                trace.append({"runtime_probe": probe})
                result = json.loads(probe)
                if result["exit_code"] != 0 or result["timed_out"]:
                    raise RuntimeError("编码隔离环境预检失败")
                self.runtime_profile = json.loads(result["stdout"])
            trace.append({"runtime_environment": self.runtime_profile})
            if (self.runtime_profile["commands"].get("dot") and not task["asset_id"].startswith("tbl_")
                    and not re.search(r"时序|sequence", task.get("requirement", ""), re.I)
                    and re.search(r"类图|ER图|流程|结构图|状态", task.get("requirement", ""))):
                task["layout_engine"] = "graphviz"
            messages = [SystemMessage(content=role_skill("coding").instructions),
                        HumanMessage(content=json.dumps({**task, "runtime_environment": self.runtime_profile}, ensure_ascii=False))]
            finalize = False
            for _ in range(self.max_model_calls):
                response = (final_model if finalize else model).invoke(messages)
                finalize = False
                messages.append(response)
                if response.tool_calls:
                    executed = False
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
                        if call["name"] == "bash" and status == "success":
                            execution = json.loads(result)
                            executed |= execution.get("exit_code") == 0 and not execution.get("timed_out")
                    artifacts = sorted(str(p.relative_to(private)) for p in private.rglob("*")
                        if p.is_file() and not p.is_symlink() and p.name != "task.json"
                        and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".json"})
                    if executed and artifacts:
                        finalize = True
                        messages.append(HumanMessage(content="命令已执行成功，工作区已存在候选产物："
                            + json.dumps(artifacts, ensure_ascii=False)
                            + "。现在进入产物提交阶段，只返回 source_path/path/kind/description JSON，"
                            "不得继续重复探测；宿主会校验真实文件及模板约束，校验失败后才重新开放修复工具。"))
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
                    try:
                        source_text = source.read_text(encoding="utf-8")
                    except UnicodeError as exc:
                        raise ValueError("source_path 必须指向 UTF-8 绘图源码或表格数据，不能指向二进制图片") from exc
                    if not source_text.strip() or "\x00" in source_text:
                        raise ValueError("源码必须是非空文本")
                    if previous_text is not None and source_text == previous_text:
                        raise ValueError("修复任务尚未修改上一版源码；必须按审查反馈修复并重新生成，不能只重跑旧源码")
                    if task.get("layout_engine") == "graphviz" and source.suffix.lower() != ".dot":
                        raise ValueError("该关系图要求Graphviz自动布局；source_path须指向实际生成图片的DOT源码，不接受手写坐标绘图脚本")
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
                        if value["kind"] == "diagram" and task.get("render_constraints", {}).get("diagram_palette") == "black_white":
                            from PIL import ImageChops
                            with Image.open(output) as picture:
                                red, green, blue = picture.convert("RGB").split()
                                if ImageChops.difference(red, green).getbbox() or ImageChops.difference(green, blue).getbbox():
                                    raise ValueError("绘图必须使用黑白线条与白底，不得包含彩色像素")
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
