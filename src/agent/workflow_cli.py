"""Run/resume a complete paper job from topic, template, and optional user facts."""
import argparse
import json
from pathlib import Path

from .state import create_initial_global_state
from .workflow import PaperWorkflow
from .writing.models import create_writing_model
from .coding import CodingAgent
from .paper_routing import PAPER_TYPES


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--discipline", default="", help="专业，如旅游管理、软件工程")
    parser.add_argument("--research-domain", default="", help="研究领域，如乡村旅游、自然语言处理")
    parser.add_argument("--paper-type", choices=("auto", *PAPER_TYPES), default="auto", help="论文类型；默认按题目、领域与专业路由")
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--facts", type=Path, help="用户已有研究事实 JSON 对象；省略时只生成拟议方案")
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--end-year", type=int)
    parser.add_argument("--provider", choices=["KIMI", "DEEPSEEK"], help="选择 .env 配置组，默认读取 WRITING_MODEL_PROVIDER")
    parser.add_argument("--coding-provider", choices=["KIMI", "DEEPSEEK"], help="可选的独立绘图/编码模型配置组")
    parser.add_argument("--timeout", type=int, default=180, help="单次模型请求超时秒数")
    parser.add_argument("--instant", action="store_true", help="对支持该参数的 Kimi/DeepSeek 模型关闭 thinking")
    parser.add_argument("--chapter-page-break", action="store_true", help="每个一级章标题另起一页")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout 必须为正数")
    facts = json.loads(args.facts.read_text(encoding="utf-8")) if args.facts else {}
    if not isinstance(facts, dict):
        parser.error("--facts 必须是 JSON 对象")
    years = {k: v for k, v in {"start_year": args.start_year, "end_year": args.end_year}.items() if v is not None}
    state = create_initial_global_state(topic=args.topic, raw_doc_path=str(args.template.resolve(strict=True)),
        workspace_dir=str(args.workspace.resolve()), single_source_of_truth=facts,
        publication_year_range=years or None, discipline=args.discipline,
        research_domain=args.research_domain, paper_type=args.paper_type)
    state["layout_options"] = {"chapter_page_break": args.chapter_page_break}
    options = {"timeout": args.timeout}
    if args.instant:
        options["extra_body"] = {"thinking": {"type": "disabled"}}
    coder = CodingAgent(llm=create_writing_model(args.coding_provider, **options)) if args.coding_provider else None
    result = PaperWorkflow(llm=create_writing_model(args.provider, **options), coder=coder).invoke(state)
    print(json.dumps({"final_doc_path": result["final_doc_path"],
                      "workflow_report": result["workflow_report"],
                      "paper_profile": result["paper_profile"],
                      "literature_search_report": result.get("literature_search_report")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
