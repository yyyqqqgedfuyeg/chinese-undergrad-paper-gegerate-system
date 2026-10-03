# Chinese Undergrad Paper Generate & Edit System

> 基于 **LangGraph** 多智能体工作流与 **python-docx** 底层排版引擎的中国本科毕业设计/论文智能生成与审改系统。

> ⚠️ **当前状态**：项目正处于初期开发阶段（WIP / Alpha 未完成版本）。

---

## 💡 核心特性

- **严格格式合规（Format-First）**：精准解析高校旧版 Word 模板，无损保留独创性声明、评阅表等静态页，遵循规范三线表、标题与正文字体行距要求。
- **真·原生学术排版**：支持 Word 原生书签、动态图表交叉引用与上标角标。
- **LangGraph 多智能体工作流**：支持 ReAct 自主循环、文献检索、Mermaid 图表生成与工具重试机制。
- **高颜值流式 WebUI**：基于 FastAPI 与原生 SSE（Server-Sent Events）驱动的 Claude 风格流式交互界面。

---

## 📁 目录结构

```text
├── agent/              # 智能体核心实现（基类、排版智能体、工具库、WebUI服务）
│   ├── output_parsers/ # 按 agent 拆分的输出数据结构、解析与业务校验
│   ├── writing/        # 撰写节点接力、工具 loop、累计记录与批次落盘
│   ├── web/            # WebUI 前端静态页面（Claude 极简风格）
│   └── utils/          # 路径与环境工具
├── docs/               # 详细产品需求（PRD）、状态机规范、工作流设计文档
├── skills/             # docx 排版能力技能包与 OpenXML 规范模式
├── test/               # 测试脚本、模板构建验证用例
├── .env.example        # 环境变量配置模板
├── requirements.txt    # 项目依赖清单
├── agent.py            # 根目录 Agent 统一入口
└── webui.py            # WebUI 服务启动入口
```

---

## 🚀 快速上手

### 1. 安装依赖

```bash
git clone https://github.com/yyyqqqgedfuyeg/chinese-undergrad-paper-gegerate-system.git
cd chinese-undergrad-paper-gegerate-system
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `.env.example` 为 `.env`，并配置您的 DeepSeek API Key：

```bash
cp .env.example .env
```

在 `.env` 中填写：
```env
DEEPSEEK_API_KEY=your_deepseek_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
```

### 3. 运行体验

- **启动 WebUI 服务**：
  ```bash
  python webui.py
  ```
  浏览器访问 `http://127.0.0.1:8000` 即可使用。

- **快速体验排版生成**：
  ```bash
  python gen_zuoye.py
  ```

---

## 📄 详细文档

### 顺序接力撰写 Agent

`WritingAgent` 从现有 `outline_plan` 中按顺序领取叶子标题，每批最多 3 个；父标题
只参与结构和完成状态计算。每批使用独立模型对话，内部执行有界的模型→工具→模型循环，
批次通过校验并落盘后才进入下一批，全程不并行撰写。

```python
from agent import WritingAgent

# state 已包含 topic、workspace_dir、single_source_of_truth、outline_plan、bib_pool。
# workspace_dir 应当是这个项目本次生成专用的目录。
writer = WritingAgent()  # 使用 .env 模型配置，自动加载项目 skills/*/SKILL.md
writer.invoke(state)
print(state["writing_report"])
print(state["writing_manifest_path"])
```

`agent/writing/` 集中保存该模块的调度、输出结构、工具、提示词与提交逻辑。
状态新增 `writing_records`（累计记录）、`writing_manifest_path` 和 `writing_report`。
每条记录包含：

```text
section_id / title            具体标题及编号
summary / key_facts           本节讲了什么、供后文承接的术语与论述
content / content_path        完整 Markdown 正文及工作目录相对路径
content_sha256 / node_index   正文校验摘要、产出批次
assets                       图表标识、说明、类型、源代码路径和导出路径
citations                    实际引用的文献 key
```

下一批获得所有历史记录的标题、摘要、关键事实和产物路径，以及上一节末尾 500 字；
需要详细内容时通过 `read` 读取原文。完整正文仍累积保存在 state 和 manifest，
但不会在每次模型调用时全量重复传输。这里的写作记录不会写回唯一事实源。

节点默认拥有绑定本次工作目录的 `bash/read/write/edit` 工具。`bash` 可生成并运行
绘图脚本、HTML 页面，调用本地浏览器或绘图库导出图片；进程使用当前 Python 环境，
返回退出码和超时信息，不自动重放失败命令。绘图和截图需要运行环境具备相应依赖，
系统提示会提供已检测到的 Python、Node 和浏览器路径。bash 是执行工具，并非系统沙箱。
可通过 `skills=[Skill(...)]` 替换默认技能，或与
`agent.writing.tools.load_project_skills()` 的结果合并；同名基础工具优先使用本次目录版本。

正文保存到 `writing/sections/<section_id>.md`，图表源文件和导出图片放在
`writing/assets/`。`writing/manifest.json` 是每批的提交点，记录产物和接力统计。
程序检查标题是否完整且顺序正确、正文长度（目标的 60%-200%，按非空字符近似）、
文献 key、规划图表覆盖、图表引用以及图片文件存在和签名。此检查不等同于学术语义审校。
正文引用沿用 `[[REF_CITE:key]]`、`[[REF_FIG:id]]`、`[[REF_TABLE:id]]`，留给装配阶段编译。

默认每批最多 12 次模型调用、30 次工具调用、2 次输出修复，可通过构造参数调整。
失败批次不标记完成；此前已提交批次保留，重新用相同输入和工作目录调用即可续跑。
再次调用已完成任务不会重复请求模型。事实源、大纲或文献池改变时需使用新工作目录，
以免沿用旧上下文。同一工作目录不支持同时运行多个撰写任务。
`writer.graph` 可作为 `PaperGlobalState` 子图嵌入上层图；直接嵌入时应按批次数设置
上层 `recursion_limit`（建议至少 `4 + 2 * 批次数`，并加上上层节点数），`invoke` 会自动设置。

验证命令（真实测试仅 4 节，每节约 180 字，覆盖 3+1 接力、状态图、网页和 PNG 导出）：

```bash
python -m unittest test.test_writing_agent -v
python -m test.test_writing_agent_real
```

真实测试读取根目录 `.env`，产物及报告保存在 `test/render/writing-real-<timestamp>/`。
为适应当前真实服务的 3 RPM 配额，验收脚本默认将模型请求间隔设为 21 秒；
可用 `WRITING_TEST_REQUEST_INTERVAL` 调整。生产调用应按模型服务配额配置客户端限流与重试。

#### 完整 DOCX 验收

`test/test_writing_docx_real.py` 进一步覆盖 11 个叶子标题（3+3+3+2）、实际图表、完整论文、
关键逻辑审查、DOCX 装配和 PDF 渲染。先运行 `test/writing_reference.py` 中的 SQLite 参考实现，
验证状态、权限、时间边界、资源互斥，以及 20 轮两个独立连接的并发抢占；这些实际结果作为
事实源输入模型。论文明确区分已运行的服务类、静态网页原型和未实现的生产能力。

表格资产为 UTF-8 JSON，格式为 `{"columns":["列名"],"rows":[["字符串单元格"]]}`，
导出时转为可编辑的原生 Word 三线表。图片嵌入 DOCX，图表引用转为书签与 REF 域，
参考文献按正文首次出现顺序编排。导出器会核对所有正文片段、图表数量和表格单元格。

```bash
# DOCX 装配依赖（隔离安装，不影响 Python 依赖）
npm install --prefix .tools/docx docx
# PDF/页面预览还需系统安装 LibreOffice、Poppler 和中文字体（推荐 Noto CJK）。
python -m unittest test.test_writing_agent test.test_writing_docx -v
python -m test.test_writing_docx_real
# 中断后使用打印出的运行目录续跑
python -m test.test_writing_docx_real --workspace test/render/writing-docx-<timestamp>
```

完整测试优先读取 `.env` 的 `KIMI_*` 配置（存在时），否则使用 `DEEPSEEK_*`；报告记录
实际 endpoint host 和 model，不用环境变量前缀冒充模型名称。通用撰写器默认使用 DeepSeek，
可设置 `WRITING_MODEL_PROVIDER=KIMI` 或显式传入 `create_writing_model("KIMI")`。

产物位于运行目录的 `output/`，包括 DOCX、PDF 和用于核查的纯文本；`preview/` 保存逐页 PNG。
`semantic-review.json` 保存独立模型对七项关键逻辑的判断；`evidence/` 保留实际验证结果、
参考实现源码和数据库文件。`docx-test-report.json` 记录机器检查结果，页面仍需打开目检，
只有目检完成后才能将 `visual_review` 标记为通过。

也可单独导出已有完整 state：

```python
from agent.writing import export_docx

report = export_docx(state, "output/paper.docx", abstract="已核验的摘要内容", keywords=["预约", "一致性"])
```

### 无工具大纲 Agent

`OutlineAgent` 读取题目与已有事实源，生成符合 `SectionPlan` 结构的完整目录。
`outline_plan` 按目录顺序包含章标题（`1`）、二级标题（`1.1`）和三级标题（`3.1.1`）。
第一、二章保留到二级，后续系统分析、设计、实现、测试等核心章节细分到三级。
父标题的 `target_words` 为 0，写作字数分配到叶子小节。软件系统的数据库设计
必须规划 ER 图及具体数据表结构三线表；已有 `db_schemas` 中的表必须全部覆盖。
模型使用 JSON mode，不挂载工具或技能。编号、字数、初始状态和字段通过校验后，
`invoke` 原地更新传入的全局 state 的 `outline_plan`；调用或校验失败时保留原状态。
可将 `agent.graph` 作为子图接入上层 LangGraph，其输出只更新大纲。

解析代码集中在 `agent/output_parsers/outline_parser.py`，包含 `SectionPlanOutput`、
`OutlineOutput` 和 `parse_outline_output(output, state)`。解析器支持 JSON 文本和模型消息，
负责代码块包装处理、目录层级与字数校验，以及软件系统的 ER 图和数据表规划检查。
解析器只返回经过校验的更新字典，不修改输入 state；agent 校验成功后提交更新。
后续需要结构化输出的 agent，在此目录增加对应的 `*_parser.py` 并由该 agent 调用。

```python
from agent import OutlineAgent, create_initial_global_state

state = create_initial_global_state(
    topic="基于 Spring Boot 的高校心理咨询预约系统的设计与实现",
    single_source_of_truth={"tech_stack": {"backend": "Spring Boot 3"}},
)
OutlineAgent().invoke(state)
print(state["outline_plan"])
```

```bash
# 回归测试
python -m unittest test.test_outline_agent test.test_output_parsers -v
# 真实接口测试：显式加载项目根目录 .env，产生一次付费模型调用
python -m test.test_outline_agent_real
```

真实测试检查请求不携带工具、输出结构和全局 state 写入，
结果及完整大纲保存至 `test/outline_agent_real.log`（已被 Git 忽略）。

### 单工具文献 Agent

`LiteratureAgent`（别名 `LiteratureIndexerAgent`）读取题目、事实源和大纲，
只挂载 `search_academic_literature` 一个工具，通过全球 OpenAlex 索引检索，
不足时用 Crossref 补充。成功目标是 **15 篇中文 + 5 篇英文**；没有国家/地区限制。
旧工具的硬编码示例文献已移除；模型只产生检索词，书目字段直接来自真实接口。

不足时默认进行 **4 轮**，可设置 `max_search_rounds=2..8`。每轮要求探索新的主题、
同义词、场景或技术关键词，重复关键词不再执行，跨轮按 DOI 和规范化标题去重累计。
达到配额立即结束；轮数用尽后仍返回已有文献（允许空列表），同时给出缺口和检索记录。
轮数包含模型未正确调用工具或重复关键词的失败尝试，报告会如实记录，不能视为有效检索。
每个关键词最多取各来源相关性排序的前 50 条，再检查标题是否包含主题关键词，
避免全文边缘提及导致无关文献混入。标题匹配较保守，可能漏掉用词不同的相关文献，
通过后续轮次的同义词扩展补充。HTTP 超时 30 秒，瞬时错误最多尝试 3 次。

`invoke` 更新全局 `bib_pool` 和 `literature_search_report`，其余字段保留。
报告包含 `counts`、`shortfall`、`rounds`、`stop_reason` 和逐轮关键词/来源诊断。
`agent.graph` 可作为子图挂入上层 LangGraph。模型调用异常抛出时不提交本次状态。

```python
from agent import LiteratureAgent, create_initial_global_state

state = create_initial_global_state(
    topic="基于 Spring Boot 和 Vue 的高校心理咨询预约系统的设计与实现",
)
LiteratureAgent(max_search_rounds=4).invoke(state)
print(state["bib_pool"])
print(state["literature_search_report"])
```

可选参数 `publication_year_range` 按**发表年份**限定范围，包含起止年份。
支持只填 `start_year` 或 `end_year`；省略参数或传 `None` 则不限年份。
年份须为 1500–2100 的整数，起始年不得晚于结束年。可直接调用工具：

```python
from agent import search_academic_literature

result = search_academic_literature.invoke({
    "chinese_queries": ["心理咨询", "预约系统"],
    "english_queries": ["online counseling", "appointment scheduling"],
    "publication_year_range": {"start_year": 2020, "end_year": 2025},
})
```

使用 Agent 时，在 `create_initial_global_state` 中传入同名参数即可。
该范围会用于两种来源的服务器筛选和本地年份复核，并记录在检索报告中；
多轮扩词不会放宽年份限制，区间内文献不足时仍返回已有结果和缺口。

每条文献包含引用 `key`、题名、作者、刊物、年份、语言、DOI（可能为空）、
卷期页码（接口缺失时保留空值）、来源 ID/URL、检索词和获取时间。
`formatted` 为可直接展示或写入参考文献列表的 **GB/T 7714 风格条目**，
由上述真实元数据生成，结构为 `作者. 题名[J]. 刊物, 年份, 卷(期): 页码. DOI:标识符.`。
`document_type` 区分期刊 `[J]`、会议 `[C]`、学位论文 `[D]`，会议条目使用 `//` 连接来源。
超过三名作者截取前三名并加“等”或“et al”；完整作者仍保留在 `authors` 中。
缺失卷期页码或 DOI 时省略对应部分，不补造出版地等信息；因此元数据不完整时条目也不完整。
该字段不预设引用编号，方便后续按正文首次引用顺序编号。例如：

```python
for reference in result["bib_pool"]:
    print(reference["formatted"])
```

语言以来源字段为依据，并排除明显的标题文字冲突；缺语言字段时仅对中文标题作脚本推断，
并标记 `language_basis=title_script`。这是元数据层校验，不代表全文语言或论文质量已审查。
检索结果属于候选文献池，是否适合最终引用仍需结合论文内容审阅。

无需新增必填密钥。`.env` 中的 `OPENALEX_API_KEY`、`CROSSREF_MAILTO` 可选。
现有 `search_academic_literature` 工具参数已改为 `chinese_queries`、`english_queries` 列表，
返回结构化字典；外部旧调用需从 `topic_or_keyword/max_results` 迁移。

```bash
python -m unittest test.test_literature_agent test.test_outline_agent test.test_output_parsers -v
# 使用真实 .env 调用模型和学术 API，并独立回查 20 条文献；产生模型 API 费用
python -m test.test_literature_agent_real
# 真实年份区间测试，独立记录到 test/literature_agent_year_range_real.log
python -m test.test_literature_agent_real --start-year 2020 --end-year 2025
```

真实测试以高校心理咨询预约系统为例，要求确实得到 15+5；完整结果与回查记录保存在
`test/literature_agent_real.log`（已被 Git 忽略），不记录密钥。
部分结果、四轮检索、跨轮去重、关键词重复、空结果、HTTP 重试及来源切换由离线测试覆盖。

选型调研（2026-10-02）：

| 来源 | 调研结论与本项目采用方式 |
| --- | --- |
| [openags/paper-search-mcp](https://github.com/openags/paper-search-mcp) | 参考其统一检索入口、开放来源及去重思路；本项目直接封装 HTTP API，保持单个 LangChain 工具。 |
| [ustc-ai4science/academic-search](https://github.com/ustc-ai4science/academic-search) | 参考多语言扩词和来源记录；其知网路径依赖浏览器流程，本次未接入知网。 |
| [OpenAlex API](https://help.openalex.org/api/) / [鉴权说明](https://help.openalex.org/api/authentication/) | 可按语言检索全球文献，支持无密钥基本查询；本项目作为主来源，已实测中文召回。 |
| [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) / [GitHub 文档](https://github.com/CrossRef/rest-api-doc) | 公开 DOI 元数据补充源，无需注册；使用 `query.bibliographic`，排除缺核心字段及语言冲突记录。 |

这套方案不等同于知网、万方的完整中文收录，细分课题可能不足目标数量；通过扩词、
多来源和如实返回缺口处理，不用翻译英文题名冒充中文文献。

更多架构与技术细节请参考 `docs/` 目录：
- [产品需求文档 (PRD)](docs/PRD.md)
- [功能需求说明 (FUNCTIONAL_REQUIREMENTS.md)](docs/FUNCTIONAL_REQUIREMENTS.md)
- [工作流状态流设计 (WORKFLOW_DESIGN.md)](docs/WORKFLOW_DESIGN.md)
