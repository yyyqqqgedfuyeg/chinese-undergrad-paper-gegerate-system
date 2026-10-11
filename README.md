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
  workflow.py           大纲→文献→撰写→装配
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

先提供独立任务目录、事实源、批准模板及装配绑定。绑定格式见 [assembly-contract.md](skills/docx/references/assembly-contract.md)。锚点和原型必须来自批准模板，不能根据样式名猜测格式。

```python
from agent import PaperWorkflow

# state 包含 topic、workspace_dir、single_source_of_truth、new_template_path、assembly_contract。
# outline_plan、bib_pool 已有时直接使用，否则运行对应角色。
result = PaperWorkflow().invoke(state, abstract="已验收摘要", keywords=["关键词"])
print(result["assembly_report"])
```

也可逐个使用 `WritingAgent(...).invoke(state)` 与 `AssemblyAgent(state, contract, abstract, keywords, output_path).invoke()`。
模板准备入口为 `DocxTemplateAgent(source_path=学校模板路径, workspace_dir=任务目录)`；不能通过聊天文本授权任意宿主路径。WebUI 可设置 `PAPER_TEMPLATE_PATH` 和 `PAPER_TASK_WORKSPACE` 后使用 `python webui.py`。

任务目录结构：

```text
任务目录/
  template/                           模板分析、清洗计划、复刻与验证
  subagents/coding/<小节>/<任务ID>/    编码 subagent 可读写的唯一持久工作区
  audit/coding/<任务ID>.json           宿主保存的调用与验收记录
  writing/sections/                    宿主提交的正文
  writing/assets/<小节>/<资产>/<ID>/   宿主发布的已验收源码与产物
  writing/manifest.json                正文及资产指纹、进度、调用指标
  assembly/final.docx                  成稿
  assembly/final.verification.json     模板与内容验证证据
```

装配器逐字节保留样式、字体、主题、编号等已有部件，保留分节与页眉页脚格式。新增正文复制模板段落原型；表格复制模板表头/数据行/末行；图片使用模板图片框。缺少原型、模板指纹过期或内容被改动时失败，不套用默认样式。输出采用确定性 ZIP，重复装配结果可逐字节对比。

模板原型的字体、行距与列宽会被保留；正文增长后的分页由 Office 排版引擎计算。装配验证不等同于 Microsoft Word UI 验收，最终视觉效果应查看 PDF 预览。旧 DOCX 创建、批注、修订、脚注脚本仍保存在 skill 内，默认不授予撰写或装配 agent。

## 验证

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/python tests/Kimi真实编码与装配/run_real.py
```

第一条不调用真实模型；第二条明确调用 `.env` 中的 Kimi，验证撰写→隔离编码生成表格/图片→保留模板格式的装配，并保存完整产物与调用用量。
