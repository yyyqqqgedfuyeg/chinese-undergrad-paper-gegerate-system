# 本科论文多智能体生成系统

项目将职责与工具权限绑定。大纲规划、文献检索、撰写、编码和成稿装配分别执行；撰写模型不操作文件，编码子智能体只在隔离工作区生成资产，装配器使用已批准模板的格式原型。

## 角色与工具

| 角色 | 可调用工具 | 权限边界 |
|---|---|---|
| 大纲 `OutlineAgent` | 无 | 输出结构化大纲，由程序校验提交 |
| 文献 `LiteratureAgent` | `search_academic_literature` | 检索核验题录，不能操作文件 |
| 撰写 `WritingAgent` | `read_section`、`code_asset` | 读取已验收正文；只委派当前小节已规划资产；正文通过 JSON 提交 |
| 编码 `CodingAgent` | `bash`、`read`、`write`、`edit` | 每项资产独立工作区；运行依赖只读；无宿主项目、密钥和网络 |
| 模板准备 `DocxTemplateAgent` | `inspect_template`、`build_template`、`verify_template` | 显式绑定学校模板；在准备阶段清洗和重建样式；原文件保留 |
| 装配 `AssemblyAgent` | `inspect_assembly`、`assemble_content`、`verify_assembly` | 固定顺序执行；只消费已验收内容；不让模型重写正文或格式 |

唯一 skill 是 `skills/docx`。角色说明按需加载，工具由代码工厂绑定；skill 不再隐式附赠 Bash。运行时策略位于 `src/agent/security`。通用基类和旧工具保留为低层兼容接口，不用于以上业务角色的权限入口。

## 文件结构

```text
src/agent/
  security/             角色白名单与 Linux 进程隔离
  coding/               只负责编码的 subagent
  template/             模板准备脚本的受控入口
  assembly/             保留模板格式的确定性装配器
  writing/              正文接力、委派、产物验证和提交
  output_parsers/       大纲与文献结果校验
  workflow.py           模板→研究设计→大纲→文献→逐节撰写→摘要→装配
  research.py           研究方案、事实冻结与一致性审查
  workflow_cli.py       完整工作流命令行入口
  outline_agent.py / literature_agent.py / docx_agent.py
skills/docx/            单一技能、角色说明、原型绑定规范、底层脚本
tests/                  按中文问题组织测试
  权限越界与角色职责/
  成稿装配保留模板/
  Kimi真实编码与装配/
  大纲规划/ 文献检索/ 正文接力/ 模板提取/ 脚注交叉引用/
  support/              公共测试夹具
  历史测试产物/          迁移前的日志和产物归档
agent/、test/            旧 import 路径的兼容入口，实现不放在这里
```

每次自动测试在对应问题目录的 `runs/<时间>_<中文问题>/result.json` 记录结果。真实测试每次创建独立运行目录，源码、日志、正文、图表和装配文档保存在该目录中。历史真实脚本以 `run_` 或 `legacy_` 开头，不随单元回归自动调用 API。

## 安装与模型

Python 3.11+，Linux；编码需要 Bubblewrap（`bwrap`）。隔离不可用时直接失败，不退回宿主 Bash。绘图依赖 Pillow、matplotlib，中文图表需要系统中文字体。LibreOffice/Poppler 用于可选渲染验收。

```bash
python -m pip install -r requirements.txt
python -m pip install pytest
python -m pip install -e .
cp .env.example .env
```

填写 `KIMI_API_KEY`、`KIMI_BASE_URL`、`KIMI_MODEL`。工作流和编码默认使用 Kimi；没有人为的每分钟调用次数限制，设置了单任务轮次、工具调用数量及命令超时上限。DeepSeek 配置仍可供显式选择的独立模型使用。凭据只在宿主模型客户端读取，不传入编码进程。

## 使用

输入题目、学校 DOCX 初始模板和独立任务目录即可启动完整流程。可选提供已有技术栈、实体字段、研究方法和真实实验依据；未提供的内容只生成拟议方案，不视为已完成实现或实测结果。

```bash
.venv/bin/python -m agent.workflow_cli \
  --topic "高校预约系统的设计与实现" \
  --template /absolute/path/学校模板.docx \
  --workspace /absolute/path/本次论文 \
  --facts /absolute/path/研究事实.json
```

`--facts` 可省略；`--start-year`、`--end-year` 可限制文献年份。使用相同命令和原始输入续跑，修改题目、模板或事实请创建新任务目录。完整流程同一工作目录禁止并发执行。

```python
from agent import PaperWorkflow, create_initial_global_state

state = create_initial_global_state(
    topic="高校预约系统的设计与实现",
    raw_doc_path="/absolute/path/学校模板.docx",
    workspace_dir="/absolute/path/本次论文",
    single_source_of_truth={"tech_stack": "Python"},
)
result = PaperWorkflow().invoke(state)
print(result["final_doc_path"])
```

摘要与关键词默认从完成的正文生成并审查，也可用 `invoke(state, abstract="…", keywords=["…"])` 一起传入。已有纯净模板与 `assembly_contract` 可以直接消费，但必须通过自定义样式及原型校验；普通原始模板请通过 `raw_doc_path` 交给模板阶段。绑定格式见 [assembly-contract.md](skills/docx/references/assembly-contract.md)。

完整流程按顺序执行：

1. 检查学校模板，生成可追溯清洗计划，执行 `replace_all` 样式重建并验证，交付纯净 DOCX 与装配绑定。
2. 根据用户事实生成研究方案，记录来源，冻结选题、对象、实体及关系、技术设计、研究方法和评估计划；审查生成方案是否与用户事实冲突。
3. 校验各主体章节普遍展开到三级的大纲（第二章起，多数非本章小结的二级标题展开至少两个三级子标题；第一章、摘要、致谢等例外），检索真实文献题录；检索为空时停止，配额不足保留缺口报告。
4. 按叶子标题循环撰写，每批最多三节；按需调用编码 agent 生成图表，校验正文长度、引用、资产文件并执行事实一致性审查后提交。
5. 成稿前逐图复查实际图片、源码与正文，必要时在隔离工作区修复；审查通过后原子替换资产记录，保留旧图及审计记录。
6. 生成并审查摘要、关键词，使用纯净模板原型编排全部内容。
7. 导出 `assembly/final.docx`，重放装配并保存验证报告。

`workflow/state.json` 保存成功阶段、冻结研究事实及错误诊断；`writing/manifest.json` 是写作批次提交点。`writing/prepared-assets.json` 缓存尚未随正文提交的已生成图表，绑定输入、模板约束及文件指纹；恢复时复用，语义审查仍不可跳过。失败批次不会进入后续接力，续跑不会重复生成已提交章节。再次调用会重新验证模板、正文和资产文件并重放导出。

也可逐个使用 `WritingAgent(...).invoke(state)` 与 `AssemblyAgent(state, contract, abstract, keywords, output_path).invoke()`。
模板准备入口为 `DocxTemplateAgent(source_path=学校模板路径, workspace_dir=任务目录)`；不能通过聊天文本授权任意宿主路径。WebUI 可设置 `PAPER_TEMPLATE_PATH` 和 `PAPER_TASK_WORKSPACE` 后使用 `python webui.py`。

任务目录结构：

```text
任务目录/
  workflow/state.json                 工作流检查点、研究冻结快照和阶段诊断
  template/                           模板分析、清洗计划、复刻与验证
  subagents/coding/<小节>/<任务ID>/    编码 subagent 可读写的唯一持久工作区
  audit/coding/<任务ID>.json           宿主保存的调用与验收记录
  writing/sections/                    宿主提交的正文
  writing/assets/<小节>/<资产>/<ID>/   宿主发布的已验收源码与产物
  writing/manifest.json                正文及资产指纹、进度、调用指标
  assembly/final.docx                  成稿
  assembly/final.verification.json     模板与内容验证证据
```

装配器逐字节保留样式、字体、主题、编号等已有部件，保留分节与页眉页脚格式。新增正文复制模板段落原型；表格复制模板表头/数据行/末行；图片保留段落样式，以模板宽度和版心高度为上限等比缩放，契约可用 `image_sizing=fixed` 要求固定原型尺寸。缺少原型、模板指纹过期或内容被改动时失败，不套用默认样式。输出采用确定性 ZIP，重复装配结果可逐字节对比。

模板原型的字体与列宽会被保留；图片段落单独设置单倍行距，避免固定行距裁切图片；正文增长后的分页由 Office 排版引擎计算。装配验证不等同于 Microsoft Word UI 验收，最终视觉效果应查看 PDF 预览。旧 DOCX 创建、批注、修订、脚注脚本仍保存在 skill 内，默认不授予撰写或装配 agent。

## 验证

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python tests/Kimi真实编码与装配/run_real.py
```

第一条不调用真实模型；第二条明确调用 `.env` 中的 Kimi，验证撰写→隔离编码生成表格/图片→保留模板格式的装配，并保存完整产物与调用用量。

## State 与工具 review

| 原有缺口 | 本次实现 | 能力边界 |
|---|---|---|
| workflow 要求调用方事先准备模板和摘要 | 自动模板准备、装配契约交接及摘要生成 | 缺失必要格式原型时明确失败，不能从无格式依据的模板猜出学校要求 |
| 任意字典事实源，没有核心研究设计阶段 | 结构化研究方案、用户事实来源记录、冻结快照和跨阶段指纹检查 | 用户输入本身的真实性仍需实际研究证据支持 |
| 正文主要依赖提示词保持一致 | 每批提交前审查选题、实体、方法、实验表述、图表源码及实际图片，失败进入有限修复 | 图片审查需要支持图像输入的模型；模型审查不能证明“零幻觉”，最终排版与学术结论仍需人工验收 |
| 文献存在容易被误当成结论已核验 | 文献池格式、去重、年份、引用 key 校验；禁止从题录推断全文结论 | 现有检索器没有全文证据获取与逐句论断溯源能力 |
| 工作流缺少持久阶段状态 | 原始输入指纹、原子检查点、目录锁、失败诊断与断点续跑 | 改选题/研究方法等关键输入需要新工作区 |
| 部分 Word 模板清除样式后留有旧编号引用和第二份样式目录 | 重建编号关联样式，同步替换 stylesWithEffects | 样式规范化与 XML 验证不能替代 Word/PDF 视觉验收 |

自动化集成测试使用离线模型与题录夹具，真实执行模板清洗工具、写作批次提交及 DOCX 装配；覆盖中断续跑、输入改变、正文篡改、一致性审查拒绝及空文献池。真实 Kimi 调用和在线检索不属于离线回归的证明范围。

完整真实测试（显式读取根目录 `.env`，按配置中的实际模型调用，保存模型响应、用量和阶段检查点）：

```bash
.venv/bin/python tests/完整工作流/run_real.py
.venv/bin/python tests/完整工作流/run_real.py --resume tests/完整工作流/runs/<运行目录>
```

默认测试题目为“基于Spring Boot的校园二手交易平台”，使用仓库中 `tests/模板提取/input/附件9 正文格式模板.docx`。不能从 Linux 环境直接读取另一台 Windows 机器的桌面路径。原始模板保持不变；模型响应日志不包含 `.env` 凭据。

真实脚本还支持 `--provider KIMI|DEEPSEEK`（选择 `.env` 配置组，不保证组名就是实际模型名）、`--timeout 180`（单次请求超时）以及 `--instant`。后者通过 `thinking.type=disabled` 请求 Kimi 的 Instant 模式，参数依据 [Moonshot 官方模型卡](https://huggingface.co/moonshotai/Kimi-K2.6/blob/main/README.md)。SDK 自动重试关闭，仅对短时 HTTP 429 限流进行最多四次退避重试；每日配额耗尽、余额不足和其他错误直接保存失败状态。每次请求错误保存在 `request-errors.jsonl`，研究审查发生网络中断时保留草稿供续跑；语义审查不通过的草稿则归档并重新生成。

写作上下文包含最近三节完整正文及全部已提交章节摘要；前文读取工具只允许已提交章节，每批最多两次读取后转入正文生成。没有规划资产的批次不暴露图表工具。资产生成要求相同则复用，审查反馈导致要求改变时重新生成并重新验收。

正式入口 `python -m agent.workflow_cli` 同样支持 `--provider`、`--timeout`、`--instant`；未指定配置组时使用 `WRITING_MODEL_PROVIDER`，再回退到 KIMI。图表密集批次会减少连续小节数，为事实审查和修改保留调用预算。CodeAgent 在隔离环境预检运行依赖并复用结果，命令成功且存在候选产物后转入无工具的 JSON 提交阶段；宿主验证失败时重新开放修复工具。

`--instant` 也适用于支持 `thinking.type=disabled` 的 DeepSeek Flash，参数依据 [DeepSeek 官方文档](https://api-docs.deepseek.com/guides/thinking_mode/)。模型选择与思考开关不改变文件验收或事实一致性审查。批次拒绝原因保存在 `writing/last-batch-error.json`，重试时与未提交资产一起恢复；图表源码必须为 UTF-8 文本，不能用 PNG 冒充源码。

“普遍包含三级标题”的执行定义是：除相关理论与技术章外，每个主体章节中，多数非本章小结的二级标题展开为至少两个三级子标题；独立的限制说明可保持二级，第一章、相关理论与技术、摘要、致谢、总结展望等章节例外。完整流程会将模型多出的纯结构容器展开为并列三级任务，保存原始草稿和编号映射；禁止丢失带正文或资产的父节点。过长的默认篇幅按原分配比例缩放至约12000字，再进行层级、资产与语义审查。

导出时保留模板样式及其他文档设置；包含目录域的模板仅额外启用 `updateFields` 并将目录域标记为待刷新，以便 Word 打开时更新目录。最终页码仍取决于实际排版软件。图片在批次提交前以实际渲染文件参与审查，裁切、严重遮挡或事实冲突会阻止提交，并通过持久化反馈触发修复。

真实成稿可用 `/usr/bin/python3 tests/完整工作流/render_pdf.py <final.docx> <预览目录>` 生成 PDF（需安装 LibreOffice 与 UNO）；在内存中刷新目录和域，仅输出 PDF 及渲染报告，不重存 DOCX。图表齐备后写作工具进入正文提交阶段，批次验收失败才重新开放图表修复，以避免模型反复要求无变化的“最终复核”。

正式 CLI 与真实测试脚本均支持 `--coding-provider KIMI|DEEPSEEK`，将写作/审查模型与图表编码模型分别配置。环境有 Graphviz (`dot`) 时编码器可用自动布局；这是可选系统依赖，可通过 `apt-get install graphviz` 安装，隔离编码环境不自行安装软件。图表修复会复制上一版源码到独立工作区，并在发布前重新验证文件。

一致性审查同时读取冻结研究方案和此前已验收章节的摘要、关键事实（`prior_design`）。前文已明确、且不违背冻结方案的设计细化可作为后续测试预期的依据，但不能升级成实测证据。审查草稿若将“无冲突/已撤回”的观察错误列入问题，会再次核实后只保留实际问题。

离线修订与排版：正文引用使用上标，参考文献条目使用正文样式且不进入大纲，图片段落强制单倍行距。`--chapter-page-break` 开启各大章另起一页。大纲的理论与技术章仅保留二级标题，设计与测试模块名称对应。标题、图表名及写作内容应简短，不使用括注或多重需求编号。

已有完整正文可通过 `tests/完整工作流/revise_offline.py SOURCE_RUN NEW_RUN PLAN_JSON` 在新工作区按显式编辑计划修改并导出，无需 `.env`，脚本禁止网络请求。旧稿、旧图表及审查记录保留；新稿重新计算内容与资产指纹，不继承旧内容的语义通过结论。示例编辑计划为 `tests/完整工作流/revisions/concise-campus.json`。

装配新增结构与排版验收：清理空前言/附录及其专属空分节，拒绝空标题和空章节；目录按实际标题重建，使用书签跳转及页码域，并在本地排版后把页码缓存写回 DOCX。最终稿无需依赖阅读器首次刷新才能显示目录。需要修改目录标题或结构时重新装配；只改变分页可更新域。本地渲染器也检查纯空白页，保留源码装配稿和最终稿的独立指纹。

论文绘图默认采用黑字、黑线、白底；编码发布工具检查 `diagram_palette=black_white` 并拒绝彩色图。此限制针对示意图，不用于伪造或更改真实系统截图。需要本地排版环境：LibreOffice Writer、python3-uno、poppler-utils；不依赖模型额度。
