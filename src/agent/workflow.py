"""Durable paper workflow: template → research → outline → literature → writing → export."""
from copy import deepcopy
import json
from hashlib import sha256
from pathlib import Path

from .outline_agent import OutlineAgent
from .literature_agent import LiteratureAgent
from .writing import WritingAgent
from .coding import CodingAgent
from .assembly import AssemblyAgent
from .writing.models import create_writing_model
from .writing.storage import atomic_write, validate_records
from .research import (ResearchAgent, assert_research_lock, digest, freeze_research,
                       json_response, review_consistency)
from .template.preparation import TemplatePreparationAgent, validate_contract
from .output_parsers.literature_parser import parse_literature_output
from .output_parsers.outline_parser import validate_outline_depth
from .literature_tool import PublicationYearRange


class PaperWorkflow:
    """One workspace per input. Completed stages and writing batches survive failures.

    invoke never mutates caller state; workflow/state.json is the durable checkpoint.
    Use the same original input to resume. Changed inputs require a new workspace.
    """
    def __init__(self, llm=None, searcher=None, *, template=None, research=None,
                 outline=None, literature=None, writer=None, coder=None):
        self.llm = llm if llm is not None else create_writing_model()
        self.template = template if template is not None else TemplatePreparationAgent(self.llm)
        self.research = research if research is not None else ResearchAgent(self.llm)
        self.outline = outline if outline is not None else OutlineAgent(llm=self.llm)
        self.literature = literature if literature is not None else LiteratureAgent(llm=self.llm, searcher=searcher)
        self.coder = coder or getattr(writer, "coder", None) or CodingAgent(llm=self.llm)
        self.writer = writer if writer is not None else WritingAgent(llm=self.llm, coder=self.coder, max_repairs=4)

    def invoke(self, state: dict, *, abstract: str | None = None, keywords: list[str] | None = None) -> dict:
        if not isinstance(state.get("topic"), str) or not state["topic"].strip():
            raise ValueError("请输入非空研究题目 topic")
        if not state.get("workspace_dir"):
            raise ValueError("请提供独立 workspace_dir")
        if (abstract is None) != (keywords is None):
            raise ValueError("摘要和关键词应同时提供或同时自动生成")
        if abstract is not None and (not abstract.strip() or not keywords or
                                     any(not isinstance(k, str) or not k.strip() for k in keywords)):
            raise ValueError("摘要和关键词不能为空")
        root = Path(state["workspace_dir"]).resolve()
        root.mkdir(parents=True, exist_ok=True)
        # OS lock is released on crash; no stale lock cleanup is needed.
        import fcntl
        with (root / ".workflow.lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("同一工作目录已有运行中的 workflow") from exc
            return self._run(state, root, abstract, keywords)

    def _run(self, state, root, abstract, keywords):
        inputs = deepcopy(state)
        inputs["workspace_dir"] = str(root)
        identity = {"state": inputs, "abstract": abstract, "keywords": keywords}
        for key in ("raw_doc_path", "new_template_path"):
            if state.get(key):
                identity[key + "_sha256"] = sha256(Path(state[key]).read_bytes()).hexdigest()
        fingerprint = digest(identity)
        checkpoint = root / "workflow/state.json"
        if checkpoint.exists():
            saved = json.loads(checkpoint.read_text())
            if saved["input_sha256"] != fingerprint:
                raise ValueError("工作区属于不同输入，请使用原始输入续跑或新建工作区")
            working = saved["state"]
        else:
            working = inputs
            working["workflow_report"] = {"status": "running", "completed_stages": []}
        report = working["workflow_report"]

        def save():
            atomic_write(checkpoint, json.dumps({"version": 1, "input_sha256": fingerprint,
                                                "state": working}, ensure_ascii=False, indent=2))

        def stage(name, action):
            if name in report["completed_stages"]:
                return
            report.update(status="running", current_stage=name)
            report.pop("error", None)
            save()
            # Failed stages may not commit mutated state.
            candidate = deepcopy(working)
            action(candidate)
            if name != "template":
                assert_research_lock(candidate)
            working.update({k: v for k, v in candidate.items() if k != "workflow_report"})
            report["completed_stages"].append(name)
            save()

        def prepare(s):
            if not s.get("new_template_path") or not s.get("assembly_contract"):
                self.template.invoke(s)
            validate_contract(s)

        def research(s):
            self.research.invoke(s)
            freeze_research(s)
            try:
                s["research_review"] = review_consistency(self.llm, s, s["research_design"])
            except ValueError:
                # Retain rejected drafts for audit, but do not replay them forever.
                draft = root / "research/proposal.json"
                if draft.exists():
                    draft.rename(draft.with_name("rejected-" + digest(s["research_design"])[:12] + ".json"))
                raise

        def outline(s):
            if not s.get("outline_plan"):
                self.outline.invoke(s)
            WritingAgent._tasks(s)
            validate_outline_depth(s["outline_plan"])
            s["outline_review"] = review_consistency(self.llm, s, s["outline_plan"])
            # Fail before expensive writing if planned assets have no format prototypes.
            planned = [a for t in s["outline_plan"] for a in t["planned_assets"]]
            bindings = s["assembly_contract"]["paragraphs"]
            if any(a.strip().startswith("fig_") for a in planned) and not {"figure", "figure_caption"} <= bindings.keys():
                raise ValueError("已规划图片但模板缺少图片/图题原型")
            if any(a.strip().startswith("tbl_") for a in planned) and ("table_caption" not in bindings or not s["assembly_contract"].get("tables")):
                raise ValueError("已规划表格但模板缺少表格/表题原型")

        def literature(s):
            if not s.get("bib_pool"):
                self.literature.invoke(s)
            s.update(parse_literature_output({"bib_pool": s.get("bib_pool", [])}))
            if not s["bib_pool"]:
                raise ValueError("没有取得可核验文献，不能进入写作；可用原输入重试检索")
            if s.get("publication_year_range"):
                years = PublicationYearRange.model_validate(s["publication_year_range"])
                if any(not years.contains(p["year"]) for p in s["bib_pool"]):
                    raise ValueError("文献不符合指定发表年份范围")
            s["literature_sha256"] = digest(s["bib_pool"])

        def writing(s):
            self.writer.invoke(s)
            tasks = WritingAgent._tasks(s)
            records = validate_records(root, s.get("writing_records", []), tasks, s)
            if len(records) != len(tasks):
                raise ValueError("全部叶子标题尚未完成")

        def metadata(s):
            value = {"abstract": abstract, "keywords": keywords} if abstract is not None else json_response(
                self.llm, "根据已验收正文生成中文摘要和关键词，只输出 {abstract: 非空字符串, keywords: 非空字符串数组}。"
                "关键词5至8个。若 required_fields 包含英文题目、摘要、关键词或致谢字段，也一并输出对应字段："
                "topic_en、abstract_en 为英文字符串，keywords_en 为5至8个英文词组的数组，acknowledgements 为致谢字符串。"
                "中英文语义必须对应；致谢不能编造姓名、机构或已有调研经历。"
                "不得新增事实；方案写为方案，没有实验证据不得宣称系统已实现或测试已通过。",
                {"required_fields": list(s["assembly_contract"]["fields"].values()), "research": s["research_lock"]["snapshot"], "sections": s["writing_records"]})
            if not isinstance(value.get("abstract"), str) or not value["abstract"].strip() or not isinstance(value.get("keywords"), list) or not value["keywords"] or any(
                    not isinstance(k, str) or not k.strip() for k in value["keywords"]):
                raise ValueError("摘要/关键词生成结果无效")
            required = set(s["assembly_contract"]["fields"].values()) & {"topic_en", "abstract_en", "keywords_en", "acknowledgements"}
            # Caller-supplied Chinese abstract still needs template-specific translations.
            if abstract is not None and required:
                translated = json_response(self.llm,
                    "根据给定中文题目、摘要、关键词生成 required_fields 指定的英文对应内容及通用致谢。"
                    "返回 JSON 对象，keywords_en 为字符串数组，其余字段为字符串。不得新增研究事实、姓名或实测结果。",
                    {"topic": s["topic"], **value, "required_fields": sorted(required)})
                value.update({key: translated.get(key) for key in required})
            for key in required:
                item = value.get(key)
                if key == "keywords_en":
                    if not isinstance(item, list) or not item or any(not isinstance(k, str) or not k.strip() for k in item):
                        raise ValueError("英文关键词生成结果无效")
                elif not isinstance(item, str) or not item.strip():
                    raise ValueError(f"元信息生成结果无效：{key}")
                s[key] = item
            s["metadata_review"] = review_consistency(self.llm, s, value)
            s["abstract"], s["keywords"] = value["abstract"], value["keywords"]

        try:
            if "template" in report["completed_stages"]:
                validate_contract(working)
            if "research" in report["completed_stages"]:
                assert_research_lock(working)
            if "literature" in report["completed_stages"] and digest(working["bib_pool"]) != working["literature_sha256"]:
                raise ValueError("已冻结文献池发生变化")
            stage("template", prepare)
            stage("research", research)
            stage("outline", outline)
            stage("literature", literature)
            stage("writing", writing)
            from .writing.asset_review import FinalAssetReviewAgent
            stage("asset_review", lambda s: FinalAssetReviewAgent(self.llm, coder=self.coder).invoke(s))
            stage("metadata", metadata)
            # Always re-verify artifacts and deterministically re-export on resume.
            assert_research_lock(working)
            validate_contract(working)
            report["current_stage"] = "assembly"
            save()
            working["assembly_report"] = AssemblyAgent(working, working["assembly_contract"],
                working["abstract"], working["keywords"], str(root / "assembly/final.docx")).invoke()
            working["final_doc_path"] = working["assembly_report"]["path"]
            if "assembly" not in report["completed_stages"]:
                report["completed_stages"].append("assembly")
            report.update(status="completed", current_stage="completed")
            report.pop("error", None)
            save()
            return working
        except Exception as exc:
            report.update(status="failed", error=f"{type(exc).__name__}: {exc}")
            save()
            raise
