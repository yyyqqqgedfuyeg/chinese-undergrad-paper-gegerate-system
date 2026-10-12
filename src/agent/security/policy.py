"""角色权限是执行约束；skill 只提供该角色的操作说明。"""
from types import MappingProxyType
from ..agent import Skill
from ..paths import project_root

ROLE_TOOLS = MappingProxyType({
    "outline": frozenset(),
    "literature": frozenset({"search_academic_literature"}),
    "writing": frozenset({"read_section", "code_asset"}),
    "coding": frozenset({"bash", "read", "write", "edit"}),
    "template": frozenset({"inspect_template", "build_template", "verify_template"}),
    "assembly": frozenset({"inspect_assembly", "assemble_content", "verify_assembly"}),
})


def authorize(role: str, name: str) -> None:
    if name not in ROLE_TOOLS[role]:
        raise PermissionError(f"{role} 无权调用 {name}")


def bind_role_tools(role, tools):
    result = {}
    for item in tools:
        authorize(role, item.name)
        if item.name in result:
            raise ValueError(f"重复工具: {item.name}")
        result[item.name] = item
    return result


def role_skill(role: str) -> Skill:
    if role not in ROLE_TOOLS:
        raise ValueError("未知角色")
    path = project_root() / "skills/docx/references/roles" / f"{role}.md"
    instructions = path.read_text(encoding="utf-8") if path.exists() else "无需 DOCX 操作。"
    if role == "template":
        instructions += "\n" + (project_root()/"skills/docx/references/template-replication.md").read_text(encoding="utf-8")
    return Skill(name="docx", description=f"DOCX 技能：{role} 角色权限视图", instructions=instructions)


def reject_extra_tools(skills):
    # 自定义说明可用，自定义可执行代码不能以同名工具绕过工厂。
    if any(s.tools for s in skills):
        raise PermissionError("角色 agent 不允许通过 skill 注入可执行工具")
