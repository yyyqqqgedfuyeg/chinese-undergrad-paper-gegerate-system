"""撰写只读已提交正文，并委派当前小节的编码任务。"""
import json
from pathlib import Path
from pydantic import Field, create_model
from langchain_core.tools import tool
from ..security.policy import bind_role_tools, role_skill


def workspace_path(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError(f"路径不在本次工作目录内: {value}")
    return path


def load_project_skills():
    return [role_skill("writing")]


def create_writing_tools(workspace_dir: str, *, tasks=(), records=(), coder=None, facts=None, issued=None, constraints=None, prepared_instructions=None, paper_context=None):
    from ..coding import CodingAgent
    from .storage import asset_id
    root = Path(workspace_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    completed = {r["section_id"]: r for r in records}
    allowed = {(t["section_id"], asset_id(a)): a for t in tasks for a in t["planned_assets"]}
    generated = issued if issued is not None else {}
    generated_instructions = prepared_instructions if prepared_instructions is not None else {}

    read_schema = create_model("ReadCommittedSection", section_id=(str, Field(
        description="只能选择当前已提交章节的 ID，不允许父标题或当前待写章节",
        json_schema_extra={"enum": list(completed)})))

    @tool(args_schema=read_schema.model_json_schema())
    def read_section(section_id: str) -> str:
        """读取已提交小节的正文；不能读取任意文件。"""
        if section_id not in completed:
            raise PermissionError("只能读取已提交小节")
        record = completed[section_id]
        # 使用已验收快照，避免任意路径入口。
        return record["content"]

    @tool
    def code_asset(section_id: str, asset_id: str, instructions: str) -> str:
        """委派编码 subagent 生成当前小节已规划的图表/原型；返回已验证资产路径。"""
        key = (section_id, asset_id)
        if key not in allowed:
            raise PermissionError("只能生成当前小节已规划的资产")
        if key not in generated or generated_instructions.get(key) != instructions:
            generated[key] = (coder or CodingAgent()).run_asset(
                {**(paper_context or {}), "section_id": section_id, "asset_id": asset_id, "requirement": allowed[key],
                 "instructions": instructions, "single_source_of_truth": facts or {},
                 "previous_source_path": generated.get(key, {}).get("source_path"),
                 "render_constraints": constraints or {}}, str(root))
            generated_instructions[key] = instructions
        return json.dumps(generated[key], ensure_ascii=False)

    return list(bind_role_tools("writing", [read_section, code_asset]).values())
