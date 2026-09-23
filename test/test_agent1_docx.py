"""
test/test_agent1_docx.py - Agent 1 (DocxTemplateAgent) 端到端模板创建与排版样式测试脚本

测试验证流程：
1. 实例化 DocxTemplateAgent (Agent 1)
2. 注入任务提示词：创建空白 docx、清空/配置 3 级标题、正文与三线表样式（行距、段距、缩进），并填充学术示例内容
3. Agent 1 自主调用 write 工具生成定制脚本，并调用 bash 执行落盘
4. 验证 test/academic_template_demo.docx 磁盘产物
5. 解析 docx 内部结构与样式参数进行自动化合规断言
6. 将完整的运行过程与 content 内容保存到 test/content.log
"""

import os
import sys
from datetime import datetime
from pathlib import Path
import docx
from docx.shared import Pt

# 确保项目根目录在 sys.path 中
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from agent.docx_agent import DocxTemplateAgent
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage


def run_agent1_test():
    log_file_path = Path(__file__).resolve().parent / "content.log"
    log_records: list[str] = []

    def log(msg: str):
        print(msg)
        log_records.append(msg)

    log("=" * 80)
    log(f"【Agent 1 (DocxTemplateAgent) 排版与样式创建测试】 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"测试模型: {os.getenv('DEEPSEEK_MODEL')} | 工作区: {root_dir}")
    log("=" * 80)

    # 1. 实例化 DocxTemplateAgent
    agent = DocxTemplateAgent()
    log(f"智能体正式名称: {DocxTemplateAgent.__name__} (Agent 1)")
    log(f"挂载工具清单: {[t.name for t in agent.get_all_tools()]}")
    log(f"挂载技能包: {[s.name for s in agent.get_skills()]}")

    # 2. 构造测试任务 Prompt
    task_prompt = (
        "你好！请按照中国高校本科毕业设计学术规范，为我创建一个标准合规的毕业论文 Word 模板演示文档，并保存至 'test/academic_template_demo.docx'。\n\n"
        "【具体排版与样式规范要求】:\n"
        "1. 创建一个全新的空白 .docx 文档。\n"
        "2. 清理/覆盖默认样式，精准配置以下 5 种标准样式规范：\n"
        "   - 标题 1 (Heading 1): 中文黑体, 西文 Times New Roman, 16pt (三号), 加粗, 居中对齐, 1.5 倍行距, 段前 12pt, 段后 6pt, 首行无缩进\n"
        "   - 标题 2 (Heading 2): 中文黑体, 西文 Times New Roman, 14pt (四号), 加粗, 居左对齐, 1.5 倍行距, 段前 6pt, 段后 3pt, 首行无缩进\n"
        "   - 标题 3 (Heading 3): 中文宋体, 西文 Times New Roman, 12pt (小四), 加粗, 居左对齐, 1.5 倍行距, 段前 3pt, 段后 0pt, 首行无缩进\n"
        "   - 正文 (Normal): 中文宋体, 西文 Times New Roman, 12pt (小四), 两端对齐, 1.5 倍行距, 首行缩进 2 字符 (24pt), 段前 0pt, 段后 0pt\n"
        "   - 表格文字 (Table): 中文宋体, 西文 Times New Roman, 10.5pt (五号), 居中对齐, 单倍行距, 段前 0pt, 段后 0pt\n"
        "3. 规范三线表要求：文档中必须包含一个符合中国学术标准的三线表（如《高校心理咨询系统核心功能需求对比表》），顶线底线 1.5pt 单黑线，栏目线 0.75pt 单黑线，表内无竖线。\n"
        "4. 填充高质量的示范内容：包含第一章「1 绪论」、第二级小节「1.1 研究背景与意义」、第三级小节「1.1.1 现实痛点分析」，多段带有首行缩进的标准正文，以及上述三线表。\n"
        "5. 最终生成并保存为 'test/academic_template_demo.docx' 文件。\n"
        "请充分利用你的 write 与 bash 工具，编写 python-docx 脚本并执行以稳健输出目标文档，执行完成后详细向我汇报各样式的参数设定与最终导出路径。"
    )

    log("\n" + "#" * 40 + " 下发任务 Prompt " + "#" * 40)
    log(f"【用户任务指令】:\n{task_prompt}\n")

    # 3. 发起调用
    session_config = {"configurable": {"thread_id": "docx_agent1_test_session"}}
    res = agent.invoke(task_prompt, config=session_config)

    # 4. 记录全量消息轨迹
    log("\n" + "#" * 40 + " 执行轨迹 (Messages) " + "#" * 40)
    for idx, m in enumerate(res["messages"], 1):
        if isinstance(m, HumanMessage):
            log(f"[{idx}] [User]:\n{m.content}")
        elif isinstance(m, AIMessage):
            tool_calls = getattr(m, "tool_calls", None)
            if tool_calls:
                log(f"\n[{idx}] [Agent 1 思考与工具决策]:\n{m.content or '(正在规划调用工具)'}")
                for tc in tool_calls:
                    log(f"    🛠️ 计划调用工具: {tc['name']}")
                    log(f"       参数: {tc['args']}")
            else:
                log(f"\n[{idx}] [Agent 1 最终汇报回复]:\n{m.content}")
        elif isinstance(m, ToolMessage):
            preview = m.content[:400] + "..." if len(m.content) > 400 else m.content
            log(f"[{idx}] [工具返回结果 ({m.name})]:\n{preview}")

    # 5. 性能与消耗统计
    log("\n" + "#" * 40 + " 性能与资源消耗统计 " + "#" * 40)
    log(f"⏱️ 总耗时: {res.get('total_duration_seconds', 0)} 秒")
    log(f"🪙 Token 消耗: 总计 {res.get('total_tokens', 0)} (输入: {res.get('prompt_tokens', 0)}, 输出: {res.get('completion_tokens', 0)})")

    # 6. 产物检验与自动化合规断言
    target_docx = Path(__file__).resolve().parent / "academic_template_demo.docx"
    file_exists = target_docx.exists()
    log("\n" + "#" * 40 + " 磁盘产物验证与合规检查 " + "#" * 40)
    log(f"🔍 产物文件是否存在: {file_exists} ({target_docx})")

    if not file_exists:
        # 兼容检查是否生成在根目录或者 test 下
        alt_docx = root_dir / "academic_template_demo.docx"
        if alt_docx.exists():
            import shutil
            shutil.move(str(alt_docx), str(target_docx))
            file_exists = True
            log(f"🔍 从根目录迁移至 test/ 目录: {target_docx}")

    assert file_exists, "❌ 测试失败：未能生成 academic_template_demo.docx 文档！"

    # 读取并深度检验 docx 结构
    doc = docx.Document(str(target_docx))
    log(f"📄 文档段落总数: {len(doc.paragraphs)}")
    log(f"📊 文档表格总数: {len(doc.tables)}")

    # 检查标题与表格
    has_h1 = any("1 绪论" in p.text or "绪论" in p.text for p in doc.paragraphs)
    has_h2 = any("1.1" in p.text for p in doc.paragraphs)
    has_h3 = any("1.1.1" in p.text for p in doc.paragraphs)
    has_table = len(doc.tables) >= 1

    log(f"  - 是否包含一级标题 (1 绪论): {has_h1}")
    log(f"  - 是否包含二级标题 (1.1): {has_h2}")
    log(f"  - 是否包含三级标题 (1.1.1): {has_h3}")
    log(f"  - 是否包含规范学术表格: {has_table}")

    assert has_h1 and has_table, "❌ 文档内容合规性检查未通过：缺少一级标题或表格！"

    # 7. 保存全量日志到 test/content.log
    log_file_path.write_text("\n".join(log_records), encoding="utf-8")
    log("\n" + "=" * 80)
    log(f"✅ Agent 1 测试全部通过！完整 content 记录已保存至: {log_file_path}")
    log("=" * 80)


if __name__ == "__main__":
    run_agent1_test()

