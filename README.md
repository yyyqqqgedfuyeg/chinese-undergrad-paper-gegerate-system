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

更多架构与技术细节请参考 `docs/` 目录：
- [产品需求文档 (PRD)](docs/PRD.md)
- [功能需求说明 (FUNCTIONAL_REQUIREMENTS.md)](docs/FUNCTIONAL_REQUIREMENTS.md)
- [工作流状态流设计 (WORKFLOW_DESIGN.md)](docs/WORKFLOW_DESIGN.md)
