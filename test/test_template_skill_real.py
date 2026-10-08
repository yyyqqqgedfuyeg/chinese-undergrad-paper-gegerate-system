"""Real .env-backed, minimal agent + docx skill integration experiment.

Run: .venv/bin/python test/test_template_skill_real.py
Optional: --out test/artifacts/template-skill/<run-name>
Logs are flushed per event, including tool calls/results and public model replies.
No private reasoning is requested or recorded. Credential values are redacted.
"""
import argparse
from datetime import datetime, timezone
import json
import shutil
from urllib.parse import urlsplit
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values, load_dotenv
from agent.docx_agent import DocxTemplateAgent
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.rate_limiters import InMemoryRateLimiter
from langchain_openai import ChatOpenAI


def run(out, provider="KIMI", request_interval=0, resume_from=None, repair_layout=False, rebuild_named_styles=False, references_test=False):
    load_dotenv(ROOT / '.env', override=True)
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = dotenv_values(ROOT / '.env')
    secrets = [v for k,v in env.items() if v and any(s in k.upper() for s in ('KEY','TOKEN','SECRET','PASSWORD'))]
    def redact(value):
        text = json.dumps(value, ensure_ascii=False, default=str)
        for secret in secrets:
            text = text.replace(secret, '[REDACTED]')
        return text
    log_file = out / 'agent-events.jsonl'
    if log_file.exists():
        raise ValueError('Use a new output directory to preserve prior logs and avoid stale artifacts')
    def record(kind, data):
        with log_file.open('a', encoding='utf-8') as f:
            f.write(redact({'time':datetime.now(timezone.utc).isoformat(),'kind':kind,'data':data}) + '\n')
        print(kind, flush=True)
    api_key = env.get(provider + '_API_KEY')
    base_url = env.get(provider + '_BASE_URL')
    model_name = env.get(provider + '_MODEL')
    if not all((api_key, base_url, model_name)):
        raise RuntimeError(f'Real run requires {provider}_API_KEY/BASE_URL/MODEL in project .env')
    record('run_start', {'provider_config_prefix':provider, 'api_host':urlsplit(base_url).hostname, 'model':model_name, 'out':str(out), 'configuration_source':'.env', 'request_interval_seconds':request_interval, 'log_scope':'Public model messages, tool arguments/results, usage; no hidden reasoning.'})
    llm = ChatOpenAI(model=model_name, api_key=api_key, base_url=base_url, timeout=180, max_retries=2)
    if request_interval > 0:
        llm.rate_limiter = InMemoryRateLimiter(requests_per_second=1/request_interval, check_every_n_seconds=0.2, max_bucket_size=1)
    agent = DocxTemplateAgent(llm=llm, enable_memory=False, default_recursion_limit=64)
    record('system_prompt', agent.get_system_prompt({}))
    source = ROOT / 'test/tmp/附件9 正文格式模板.docx'
    task = f'''目标1：使用 docx skill 复刻学校模板，并生成可用于后续论文的干净模板和字体样式存储。
源文件：{source}
所有产物只能写入：{out}
读取 skills/docx/references/template-replication.md 并实际执行其流程。
先 inspect 到 {out}/source，然后用 read 读取 summary.json（max_lines 可设为 3000）。
summary 已含段落/run 直接格式与继承属性候选，一次读取即可分析；仅在具体属性缺失时做定向查询，不要将整个 inventory 或所有 styles XML 读入上下文。inspect/summary 已由脚本完整提取，无需重新开发 XML 解析器。读取 summary 后至多两次定向查询，随后必须 write 计划并执行 build/verify，用验证失败来驱动修正。
你需要自行理解每个说明和示例段落，write 清洗计划到 {out}/cleaning-plan.json，不能只复制文件作为全部任务。
清洗全部正文说明括号、星号、叉号、示例图表标题、封面填写指导和附录指导；替换为语义清晰、全局唯一的 {{{{字段名}}}} 占位符，保留静态声明、栏目标签、编号、目录结构和图表结构。表格中的“我是表格”也是示例，使用 scope="table" 的 edit 清理成唯一占位符（索引见 table_paragraphs）；表格的边框列宽等结构保持。目录中的示例叉号也换成唯一占位符，保留域和页码缓存。页眉中的示例论文题目也替换为占位符，填写时与中文论文题目一致。
注明要求是宋体/Times New Roman 小四、1.5 倍行距的内容，清洗时按明确说明校正对应内容 run 和 spacing；有冲突记录 conflicts。封面题目填写区按三号16pt黑体，姓名等按小三15pt楷体；图表题内容按小五9pt宋体并清除红色；未明确规定的标题样式按源文件保留。
至少5个关键词、15篇参考文献至少1篇外文等内容约束存入 content_requirements，示例只用于验证占位符填写，不代表成稿论文符合这些内容约束。
执行 build 与 verify；失败可修复计划重新执行，成功后生成 values.json，填写所有占位符，输出 {out}/filled-demo.docx。示例填写内容短且可辨认，中文/英文关键词各至少5个、分号分隔；英文标题和摘要用英文，其余使用合理的中文测试内容。
不要读取 .env 或输出任何环境变量/凭据，由运行器完成模型配置。只使用 .venv/bin/python。不要自行做渲染（由外层独立验证），外层负责独立断言/XSD/渲染。verify 通过且 fill 成功后立即最终回复准确列出验证结果、冲突和限制；不要另写检查脚本或报告。
'''
    if resume_from:
        previous = Path(resume_from).resolve()
        for name in ('cleaning-plan.json','values.json'):
            shutil.copyfile(previous/name,out/name)
        record('resume_from', {'directory':str(previous),'copied':['cleaning-plan.json','values.json']})
        task = f"""继续目标1的开发测试循环。真实 docx skill 上一轮已产出完整正文/表格清洗计划与填写值；独立检查发现页眉中的「毕业设计题目」仍未清洗。本轮只修复此缺陷并重新构建全部文档。
源文件：{source}
输出目录：{out}
已有计划 {out}/cleaning-plan.json 与 {out}/values.json 从上一轮复制，正文/表格规则已通过独立格式验证，直接复用，不重新分析整个模板。
读取 skills/docx/references/template-replication.md。执行 inspect 到 {out}/source，定向查看 summary.json 的 stories。给计划添加页眉示例题目的替换（part 指定对应页眉文件，保留学校名称、run 格式和页眉结构），占位符全局唯一，填写值与已有中文论文题目一致。保留原计划 edits/conflicts/content_requirements，仅补充本次改动和依据。
然后执行 build、verify、fill，产出 replica.docx、clean-template.docx、filled-demo.docx。如有报错修复后重试。外层负责独立 XSD 与渲染；verify 通过且 fill 成功就立即回复最终结果，不开发新的检查脚本、不额外写报告、不重复读取输出。
所有写入限制在输出目录，使用 .venv/bin/python；不读取 .env，不输出环境变量或凭据。
"""
    if repair_layout:
        if not resume_from:
            raise ValueError('--repair-layout requires --resume-from')
        task = f"""继续模板测试循环，读取 skills/docx/references/template-replication.md。源模板 {source}，输出目录 {out}，既有 cleaning-plan.json 和 values.json 已复制，保持既有清洗规则和填写值。
外层逐页检查发现英文摘要（body 段81）和英文关键词（段84）的首行字符分散、文字越过右边界，原因是继承了字符网格。诊断已证明只在这两个段落设置 paragraph_properties.snapToGrid={{"val":"0"}} 即可恢复正常换行，行距仍是1.5倍、字体仍是12pt Times New Roman、源分节网格和其它格式保留。不要缩短英文填写值掩盖问题，不要改标题样式。
请你实际修改已有计划中的这两个 edit 并记录 conflicts/evidence，执行 inspect 到 {out}/source，然后 build、verify、fill 重建全部产物。需重新 inspect 是因为外层验收要求保留源格式存储；无需再读整个 summary/inventory。修复后的脚本支持 snapToGrid 的正确 XSD 插入顺序。验证通过且填写成功后直接回复最终结果；外层做 XSD 和版面边界验收，不另写检查脚本或报告。所有写入仅输出目录，不读取 .env 或输出环境变量/凭据。
"""
    if rebuild_named_styles:
        if not resume_from:
            raise ValueError('--rebuild-named-styles requires --resume-from')
        task = f"""按用户修正再次调用真实 API 测试：首先 clean 全部默认/源样式，再新增模板命名样式，使其在预设样式库中可选。
源文件 {source}，所有输出目录 {out}。既有正文/页眉清洗计划和 values.json 已复制；保留原 edits/conflicts/content_requirements 和填写值。
读取 skills/docx/references/template-replication.md 的命名样式章节，再读取 test/fixtures/annex9-style-rebuild.json（已按附件9段落准备的样式定义候选，可依据模板调整）。由你把 style_rebuild 合入输出目录的 cleaning-plan.json，必须采用 mode=replace_all。新增中文命名样式覆盖正文、三级标题、封面、声明、目录、摘要/关键词、图表题、参考文献、致谢、附录、表格文字、页眉、页脚；每种样式实际应用且设为样式库可见，清空旧定义而非改名。新的引擎已实现格式继承解析和旧引用清理。
执行 inspect 到 {out}/source，build、verify、fill，输出 style-catalog.json、clean-template.docx 和 filled-demo.docx。验证成功并填写完成后直接最终回复样式数量、名称和路径。外层负责独立样式检查、XSD 和渲染，不自行写额外检查脚本。仅使用 .venv/bin/python，不读取 .env、不输出凭据，所有改动仅输出目录。
"""
    if references_test:
        source = ROOT/'test/artifacts/template-skill/run-08/filled-demo.docx'
        task = f"""测试 docx skill 新能力：真正脚注、自定义脚注样式，以及正文对表格、脚注、参考文献的动态交叉引用。
源文档：{source}；所有输出只允许写入 {out}。
读取 skills/docx/references/notes-and-references.md。使用 scripts/notes_references.py，保持源文档完整并在末尾新增独立分页的「脚注与交叉引用能力测试」章节（PaperHeading1 标题）。
由你 write {out}/references-plan.json：source_sha256 取真实源文件哈希；脚注正文9pt宋体/Times New Roman、单倍行距，标记9pt上标；2条不同的真正脚注，每条都有至少一次 NOTEREF 再次引用；2张真实数据表及动态表题，两条标明虚构演示的参考文献，每张表和每条文献在正文至少被 REF 引用一次；至少一处前向引用。使用 Table_TestA、Table_TestB、Note_TestA、Note_TestB、Bib_TestA、Bib_TestB 作为书签名，表题 SEQ 标识符 SkillTable、参考文献 SkillReference。正文用自然论文句子展示引用关系。正文、脚注和表格只展示简短的演示内容，不写运行环境、域指令、样式ID或技术实现说明（这些由JSON报告记录）。测试文献明确写「虚构演示文献」而非伪造真实来源。
正文中的 REF 表号已带“表”字前缀，不要在它前面重复添加“表”字。最多一次定向源样式查询，随后直接 write 计划、apply、inspect、refresh；不要额外创建调试脚本。
源样式：PaperBody=论文正文，PaperHeading1=论文一级标题，PaperTableCaption=论文表题（先定向读取源 style-catalog.json 或 styles.xml 确认，若实际ID不同按真实值），PaperTable1=论文表格，参考文献正文同样按真实ID查找。不要假设示例ID存在。
运行 apply，输出 {out}/capability-demo.docx 及 {out}/capability-report.json，再 inspect 确认通过。按参考文档的Linux兼容流程执行 refresh 输出 {out}/capability-refreshed.docx 和 {out}/cache-refresh.json，保留原生Word域与样式。失败时修复计划并重试；成功后立即最终回复测试范围、脚注样式与引用域、产物路径、初始缓存待office更新的限制。
外层负责独立XSD、脚注位置/字体/跳转检查以及插入新目标后的编号更新实验，不由你重写验证脚本、不自行渲染。不读取 .env、不输出凭据，使用 .venv/bin/python。
"""
    record('task', task)
    start = time.monotonic()
    usage = {'input_tokens':0, 'output_tokens':0, 'total_tokens':0}
    try:
        stream = agent.graph.stream(agent._normalize_input(task), config={'recursion_limit':64}, stream_mode='updates')
        for update in stream:
            for node,state in update.items():
                for m in state.get('messages',[]):
                    data = {'node':node,'type':m.type,'content':m.content}
                    if isinstance(m,AIMessage):
                        data['tool_calls'] = m.tool_calls
                        data['usage'] = m.usage_metadata
                        for k in usage:
                            usage[k] += (m.usage_metadata or {}).get(k,0)
                    if isinstance(m,ToolMessage):
                        data.update(name=m.name, tool_call_id=m.tool_call_id, status=m.status)
                    record('message',data)
            if references_test:
                expected_refs=('references-plan.json','capability-demo.docx','capability-report.json','capability-refreshed.docx','cache-refresh.json')
                if all((out/name).is_file() for name in expected_refs):
                    applied=json.loads((out/'capability-report.json').read_text())
                    refreshed=json.loads((out/'cache-refresh.json').read_text())
                    if applied.get('passed') and refreshed.get('passed'):
                        record('completion_condition_met', {'reason':'Requested apply/inspect/refresh artifacts exist and both reports passed; independent acceptance follows outside the agent.', 'public_final_reply':'Not required: runner ended the tool loop on artifact completion.'})
                        stream.close()
                        break

        # Independent outer assertion: the agent cannot self-certify completion.
        expected = ('references-plan.json','capability-demo.docx','capability-report.json','capability-refreshed.docx','cache-refresh.json') if references_test else ('replica.docx','clean-template.docx','cleaning-plan.json','verification.json','values.json','filled-demo.docx','source/inventory.json','clean-format/inventory.json')
        for filename in expected:
            if not (out/filename).is_file():
                raise AssertionError(f'Missing artifact: {filename}')
        if not json.loads((out/('capability-report.json' if references_test else 'verification.json')).read_text())['passed']:
            raise AssertionError('Agent verification did not pass')
        result = {'status':'passed','duration_seconds':round(time.monotonic()-start,3),'usage':usage}
        record('run_complete',result)
        (out/'run-result.json').write_text(redact(result)+'\n',encoding='utf-8')
    except BaseException as exc:
        record('run_error', {'type':type(exc).__name__,'error':str(exc),'traceback':traceback.format_exc(),'usage':usage})
        raise
    print('Artifacts:', out, flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', default=str(ROOT/'test/artifacts/template-skill'/datetime.now().strftime('%Y%m%d-%H%M%S')))
    p.add_argument('--provider', choices=('KIMI','DEEPSEEK'), default='KIMI', help='Select .env variable prefix; endpoint/model are read from that group')
    p.add_argument('--request-interval', type=float, default=0, help='Optional minimum seconds between model requests')
    p.add_argument('--resume-from', help='Reuse a previous real-agent plan/values for a focused header correction')
    p.add_argument('--repair-layout', action='store_true', help='Apply the English paragraph grid correction in a focused real-agent iteration')
    p.add_argument('--rebuild-named-styles', action='store_true', help='Clean all old styles and create visible applied template styles using the real agent')
    p.add_argument('--references-test', action='store_true', help='Test native footnotes and cross references with the real model')
    args = p.parse_args()
    run(args.out, args.provider, args.request_interval, args.resume_from, args.repair_layout, args.rebuild_named_styles, args.references_test)
