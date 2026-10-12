"""成稿装配 agent：固定 inspect → assemble → verify，无模型重写或 shell。"""
import copy
from hashlib import sha256
import json
from pathlib import Path
import tempfile

from langchain_core.tools import tool
from ..security.policy import bind_role_tools
from .engine import assemble, package, parse, text, NS


class AssemblyAgent:
    role = "assembly"

    def __init__(self, state: dict, contract: dict, abstract: str, keywords: list[str], output_path: str):
        self.state = copy.deepcopy(state)
        self.contract = copy.deepcopy(contract)
        self.abstract = abstract
        self.keywords = list(keywords)
        self.template = Path(state.get("new_template_path") or state.get("raw_doc_path", "")).resolve(strict=True)
        if not self.template.is_file():
            raise ValueError("必须提供已批准的模板")
        root = Path(state["workspace_dir"]).resolve()
        output = Path(output_path).resolve()
        if not output.is_relative_to(root / "assembly") or output == self.template:
            raise PermissionError("成稿只允许写入任务 assembly/ 目录")
        self.output = output
        self.report = None
        self.template_hash = sha256(self.template.read_bytes()).hexdigest()

    def _check_template(self):
        if sha256(self.template.read_bytes()).hexdigest() != self.template_hash:
            raise ValueError("模板在装配期间发生变化")

    def get_all_tools(self):
        @tool
        def inspect_assembly() -> dict:
            """只读检查已绑定模板与内容清单，不接受任意路径。"""
            self._check_template()
            doc = parse(package(self.template)["word/document.xml"])
            return {"template_sha256": self.template_hash,
                    "paragraphs": [text(p) for p in doc.find("w:body", NS).findall("w:p", NS)],
                    "sections": len(self.state.get("writing_records", []))}

        @tool
        def assemble_content() -> dict:
            """使用已绑定模板原型装配已验收内容；不接收正文或格式修改参数。"""
            self._check_template()
            data, report = assemble(self.template, self.contract, self.state, self.abstract, self.keywords)
            self.output.parent.mkdir(parents=True, exist_ok=True)
            temp = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.output.parent, delete=False) as handle:
                    temp = Path(handle.name); handle.write(data)
                self._check_template()
                temp.replace(self.output)
            finally:
                if temp:
                    temp.unlink(missing_ok=True)
            self.report = {**report, "path": str(self.output), "output_sha256": sha256(data).hexdigest()}
            return self.report

        @tool
        def verify_assembly() -> dict:
            """重放确定性装配并逐字节验证成稿、源模板指纹和内容。"""
            self._check_template()
            expected, report = assemble(self.template, self.contract, self.state, self.abstract, self.keywords)
            if not self.output.is_file() or self.output.read_bytes() != expected:
                raise ValueError("成稿与已验收内容/模板不一致")
            result = {**report, "path": str(self.output), "output_sha256": sha256(expected).hexdigest(),
                      "deterministic_replay_identical": True}
            self.output.with_suffix(".verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
            return result

        return list(bind_role_tools(self.role, [inspect_assembly, assemble_content, verify_assembly]).values())

    def invoke(self) -> dict:
        tools = {t.name: t for t in self.get_all_tools()}
        tools["inspect_assembly"].invoke({})
        tools["assemble_content"].invoke({})
        return tools["verify_assembly"].invoke({})
