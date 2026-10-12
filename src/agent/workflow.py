"""职责有界的论文工作流；模板与事实源由调用方明确交付。"""
from copy import deepcopy
from pathlib import Path
from .outline_agent import OutlineAgent
from .literature_agent import LiteratureAgent
from .writing import WritingAgent
from .coding import CodingAgent
from .assembly import AssemblyAgent
from .writing.models import create_writing_model


class PaperWorkflow:
    """大纲→文献→撰写(委派编码)→装配；已存在的验收阶段可继续使用。"""
    def __init__(self, llm=None, searcher=None):
        self.llm = llm if llm is not None else create_writing_model("KIMI")
        self.outline = OutlineAgent(llm=self.llm)
        self.literature = LiteratureAgent(llm=self.llm, searcher=searcher)
        self.writer = WritingAgent(llm=self.llm, coder=CodingAgent(llm=self.llm))

    def invoke(self, state: dict, *, abstract: str, keywords: list[str]) -> dict:
        working = deepcopy(state)
        if not working.get("assembly_contract") or not working.get("new_template_path"):
            raise ValueError("请先完成模板准备并提供 assembly_contract 与 new_template_path")
        if not working.get("outline_plan"):
            self.outline.invoke(working)
        if not working.get("bib_pool"):
            self.literature.invoke(working)
        self.writer.invoke(working)
        output = Path(working["workspace_dir"]).resolve()/"assembly/final.docx"
        report = AssemblyAgent(working, working["assembly_contract"], abstract, keywords, str(output)).invoke()
        working["assembly_report"] = report
        return working
