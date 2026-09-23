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

更多架构与技术细节请参考 `docs/` 目录：
- [产品需求文档 (PRD)](docs/PRD.md)
- [功能需求说明 (FUNCTIONAL_REQUIREMENTS.md)](docs/FUNCTIONAL_REQUIREMENTS.md)
- [工作流状态流设计 (WORKFLOW_DESIGN.md)](docs/WORKFLOW_DESIGN.md)
