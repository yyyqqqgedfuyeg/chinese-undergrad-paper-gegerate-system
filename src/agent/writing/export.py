"""兼容导出入口，交由保格式装配 agent 执行。"""

def export_docx(state: dict, output_path: str, abstract: str, keywords: list[str], contract: dict | None = None) -> dict:
    """兼容导出入口；必须绑定模板，禁止回退为默认格式的新文档。"""
    from ..assembly import AssemblyAgent
    binding = contract or state.get("assembly_contract")
    if not binding:
        raise ValueError("缺少 assembly_contract；请先准备模板原型绑定")
    return AssemblyAgent(state, binding, abstract, keywords, output_path).invoke()
