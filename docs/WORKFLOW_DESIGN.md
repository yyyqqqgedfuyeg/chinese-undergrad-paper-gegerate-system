# 工作流架构与状态机设计说明书 (Workflow Design)

- **文档版本**：v1.0
- **更新日期**：2026-09-15
- **关联文档**：[PRD.md](file:///e:/CODING/PYTHON/chinese-undergrad-paper-gegerate-system/PRD.md) | [FUNCTIONAL_REQUIREMENTS.md](file:///e:/CODING/PYTHON/chinese-undergrad-paper-gegerate-system/docs/FUNCTIONAL_REQUIREMENTS.md)
- **技术框架**：基于 **LangGraph** 的有向状态图与顺序链（StateGraph & Sequential Execution Chain）

---

## 1. 整体工作流全景设计

系统包含两大工作流：
1. **创作模式（Creation Workflow）**：从“选题 + 学校模板”出发，采用**前置硬核规格固化 $\rightarrow$ 两阶段大纲规划 $\rightarrow$ 资产先导的二级小节顺序链撰写 $\rightarrow$ 底层 OpenXML 缝合**的全自动工业化生产管线。
2. **编辑模式（Editing Workflow）**：基于**自主 ReAct 智能体循环（ReAct Agent Loop）**，通过挂载批注解析、切片重写、交叉引用重编等工具，按需修改并生成版本增量。

---

## 2. 创作模式工作流（Creation Mode: 0到1全自动生成）

### 2.1 整体拓扑流程图

```mermaid
graph TD
    Start([用户输入: 选题 + 学校模板.docx]) --> Node1[1. 模板切片与样式提取节点<br>template_slicer_node]
    
    Node1 --> Node2[2. 全局规格固化与真实文献池检索<br>spec_and_bib_initializer_node]
    
    subgraph 规格硬编码落盘
        Node2 -->|落盘 spec.json| SpecFile[唯一事实源: 模块/技术栈/数据库Schema/实体]
        Node2 -->|落盘 bib_pool.json| BibFile[真实中英文参考文献候选池 (20-25篇)]
    end
    
    Node2 --> Node3[3. 两阶段大纲规划节点<br>two_stage_outline_planner_node]
    
    subgraph 两阶段大纲规划
        Node3 -.-> Step3A[阶段一: 规划 6-7 个一级大章及字数/定位]
        Step3A -.-> Step3B[阶段二: 展开所有2-3级小标题 + 明确图表埋点]
    end
    
    Node3 --> Node4[4. 资产先导的二级小节顺序链撰写器<br>sequential_section_writer_chain]
    
    subgraph 顺序链单节循环 (15-18 次迭代，每次 800-1500 字)
        direction TB
        SectionStart[进入第 i 个二级小节] --> CheckAsset{是否需要插图/插表?}
        CheckAsset -->|需要| GenAsset[资产先导工具: 运行 bash 渲染 Mermaid图 / UI截图 / 三线表]
        CheckAsset -->|无需| AssemblePrompt[组装撰写 Prompt]
        GenAsset --> AssemblePrompt
        AssemblePrompt --> CallLLM[单次调用大模型输出正文<br>(极速单次放行，严谨 Prompt 约束)]
        CallLLM --> NextSection[滑动更新上下文: 记录尾部300字与图表计数]
    end
    
    Node4 --> Node5[5. 全局交叉引用与参考文献编译器<br>cross_ref_and_bib_compiler_node]
    
    Node5 --> Node6[6. 底层 OOXML 缝合与成稿装配器<br>docx_assembler_node]
    
    Node6 --> End([输出整洁产物: output/v1.0初稿.docx + .repo/commits/ 快照])
```

---

### 2.2 核心节点详细规格设计

#### 节点 1：模板切片与样式提取 (`template_slicer_node`)
- **执行目标**：解构学校陈年 `.docx` 模板，分离静态保留页与动态排版规范。
- **输入**：用户上传的原始学校模板文件（`template/raw_template.docx`）。
- **执行逻辑**：
  1. 解压并解析 `word/document.xml` 与 `word/_rels/`，通过分节符（`w:sectPr`）与标题关键词（如“诚信声明”、“评阅表”、“答辩记录”）精准切分出**静态保留 XML 块**。
  2. 读取 `word/styles.xml`，提取正文字体（如宋体/Times New Roman）、各级标题字号磅值、行距倍数、段落首行缩进（2字符），输出为 `template/extracted_styles.json`。
  3. 剔除正文中的“*注：此处为小四宋体...*”等指导性占位文字，确立正文挂载点。
- **状态输出（State Delta）**：
  ```json
  {
    "static_sections_saved": true,
    "style_rules_path": "template/extracted_styles.json",
    "template_ready": true
  }
  ```

---

#### 节点 2：全局设计规格固化与真实文献池构建 (`spec_and_bib_initializer_node`)
- **执行目标**：**前置全量确立唯一事实源（Single Source of Truth）**，彻底杜绝后续多章节撰写中的前后矛盾；同时准备好 100% 真实的参考文献库。
- **输入**：用户论文选题、所属学科方向、补充要求。
- **执行逻辑**：
  1. **构建全局系统规格书 (`spec.json`)**：
     - 系统定位与中文全称、英文全称。
     - 角色清单（如管理员、普通用户、咨询师）。
     - 功能模块划分（树状三级功能矩阵）。
     - 技术栈选型（前端、后端、数据库、开发工具、版本号）。
     - **数据库物理结构字典（Database Schema Table）**：核心数据表名、主外键、字段名、数据类型、字段注释（如 `user`、`order`、`appointment` 等表的完整 Schema）。
     - *（若为非计算机的相近学科，如经管调研/数据分析，则固化为“研究假设、调研问卷维度、数据源特征字段、计量模型公式”）*。
     - **直接落盘写入工作区 `spec.json`，全篇只读引用**。
  2. **检索真实候选参考文献池 (`bib_pool.json`)**：
     - 根据选题核心关键词，调用联网学术接口（CrossRef / OpenAlex / 知网公开检索），精选匹配 20~25 篇真实中英文学术文献。
     - 存储标准元数据（作者、篇名、期刊、出版年、卷期、DOI），生成唯一引用 Key（如 `cite_spring_security`、`cite_vue_frontend`）。
- **状态输出（State Delta）**：
  ```json
  {
    "spec_file_path": "project_spec.json",
    "bib_pool_path": "assets/bib_pool.json",
    "total_bib_candidates": 22
  }
  ```

---

#### 节点 3：两阶段大纲规划 (`two_stage_outline_planner_node`)
- **执行目标**：宏观与微观平衡，构建包含具体图表埋点与字数规划的高质量大纲树。
- **两阶段执行逻辑**：
  1. **阶段一（宏观骨架）**：
     - 规划标准的 6~7 个一级大章（绪论 $\rightarrow$ 关键技术 $\rightarrow$ 需求分析 $\rightarrow$ 总体设计 $\rightarrow$ 详细实现 $\rightarrow$ 系统测试 $\rightarrow$ 总结与展望）。
     - 明确各章核心职能与建议字数分配（如第4章设计 3500字、第5章实现 4000字）。
  2. **阶段二（微观展开与资产埋点）**：
     - 注入 `spec.json`，为每个一级大章批量展开 2 级标题和 3 级标题（全篇约 15~18 个二级小节）。
     - **显式标定资产生成需求**：在每个二级小节元数据中，清晰注明该小节需要绘制什么图、插入什么表。
       - 例：`3.2 业务流程分析` $\rightarrow$ 标记需求资产：`fig_3_1: 用户预约业务流程图 (Mermaid)`
       - 例：`4.3 数据库设计` $\rightarrow$ 标记需求资产：`table_4_1: 数据库核心表字典 (三线表)`
       - 例：`5.2 核心功能实现` $\rightarrow$ 标记需求资产：`ui_5_1: 用户服务大厅前端界面 (Playwright 渲染截图)`
- **状态输出（State Delta）**：
  ```json
  {
    "outline_tree": [
      {
        "chapter_id": 3,
        "title": "第3章 系统需求分析",
        "sections": [
          {
            "section_id": "3.1",
            "title": "3.1 系统可行性分析",
            "target_words": 1000,
            "assets_needed": []
          },
          {
            "section_id": "3.2",
            "title": "3.2 业务流程分析",
            "target_words": 1200,
            "assets_needed": [
              {
                "id": "fig_3_1",
                "type": "mermaid",
                "caption": "用户核心业务流程图"
              }
            ]
          }
        ]
      }
    ]
  }
  ```

---

#### 节点 4：资产先导的二级小节顺序链撰写器 (`sequential_section_writer_chain`)
- **执行目标**：按顺序链依次执行 15~18 次小节撰写，每次产出 800~1,500 字，最终累积达到 1.2w~1.5w 字的饱满正文。
- **设计哲学**：**极速单次放行（完全信任单次输出，无额外反思重试开销，依赖极度严密的前置 Prompt 约束）**。
- **单小节撰写循环的执行步骤**：
  1. **资产先导工具调用（Just-in-time Asset Generation）**：
     - 若当前小节包含资产需求：
       - **Mermaid 架构图/流程图**：根据 `spec.json` 生成 `.mmd` 源码，调用 `bash_executor` 执行 `mmdc` 输出无损 PNG 并分配图编号（如“图 3-1”）。
       - **现代前端 UI 原型截图**：针对第 5 章的界面展示，将系统业务字段注入预置的前端 Tailwind 模板中，调用 `bash_executor` 启动无头浏览器（Playwright）在本地秒级截取 1080P 高清真实界面图（如“图 5-2”）。
       - **标准学术三线表**：直接从 `spec.json` 读取数据字典或测试用例，生成三线表结构。
  2. **双轨精简滑动上下文组装**：
     - Prompt 注入内容严格控制在轻量级（~2k tokens）：
       - ① `spec.json`（全局事实底座）
       - ② 当前小节标题与核心论证要点
       - ③ 刚刚生成好的图表编号与结构摘要（让大模型“看图说话”，在正文中对图表内容深度分析）
       - ④ 上一小节结尾 300 字及一句话核心摘要（实现无缝承上启下）
       - ⑤ 全局图表与参考文献序号计数器
  3. **大模型推理起草**：
     - 模型在严密 Prompt 引导下输出正文，并在文中自然打入原生引用标记（如 `[[REF_FIG:fig_3_1]]`、`[[REF_CITE:cite_spring_security]]`）。
  4. **状态与上下文滑动更新**：
     - 将本节撰写内容持久化为 `temp_sections/chX_secY.md`。
     - 提取本节末尾 300 字与一句话摘要更新至全局状态，供下一小节使用。

---

#### 节点 5：全局交叉引用与参考文献编译器 (`cross_ref_and_bib_compiler_node`)
- **执行目标**：将所有分散小节的文本汇聚，执行 Word 原生交叉引用书签注入与 GB/T 7714-2015 参考文献对齐。
- **执行逻辑**：
  1. **图表原生交叉引用（Word Bookmarks & Fields）**：
     - 在每个图表的题注段落处注入 `<w:bookmarkStart w:name="_Ref_Fig_X_Y"/>`。
     - 将正文中出现的 `[[REF_FIG:fig_X_Y]]` 转换为 Word 原生域代码：
       `<w:fldSimple w:instr=" REF _Ref_Fig_X_Y \h "><w:r><w:t>图 X-Y</w:t></w:r></w:fldSimple>`。
  2. **参考文献真·上标与文末顺序自动重排**：
     - 扫描全篇正文中被引用的文献标签（`[[REF_CITE:key]]`）。
     - 按照正文中出现的**先后顺序**，重新分配自然序号：第 1 个出现的赋为 `[1]`，第 2 个赋为 `[2]`...
     - 正文引用点包裹原生 Word 上标属性：`<w:rPr><w:vertAlign w:val="superscript"/></w:rPr>`。
     - 文末自动生成符合 GB/T 7714-2015 规范的完整参考文献列表（包含全部作者、文章名、刊名、出版年、卷期页码）。

---

#### 节点 6：底层 OOXML 缝合与成稿装配器 (`docx_assembler_node`)
- **执行目标**：无损缝合老模板静态页与动态正文，生成最终规范交付文件与版本快照。
- **执行逻辑**：
  1. 将节点 1 剥离出的静态页（封面、独创性声明、评阅表）与节点 5 编译完成的正文、参考文献、致谢进行底层 OpenXML 缝合。
  2. 继承模板所有的页边距、奇偶页眉页脚、分节符设置。
  3. 调用 `bash_executor` 执行 LibreOffice 无头渲染，生成全文字段更新与 PDF 高清页面预览图。
  4. 触发版本管理引擎，创建 `commit_001_v1.0` 版本快照，生成交付文档：`output/20260915_v1.0_初稿生成.docx`。

---

## 3. 编辑模式工作流（Editing Mode: 1到N的 ReAct 自主智能体）

编辑模式采用**基于工具调用的自主 ReAct Agent 循环**，面对导师的批注与修改意见，自主推导并修改文档。

```mermaid
graph TD
    UserFeedback[用户上传: 现有论文.docx + 导师批注/文本/截图意见] --> ReActInit[ReAct Agent 启动与任务初始化]
    
    subgraph ReAct 思考-行动-观察循环 (Infinite ReAct Loop)
        ReActInit --> Thought[1. Thought: 剖析批注意图与定位目标章节]
        Thought --> Action[2. Action: 决定调用的工具]
        
        Action --> ToolBox{工具箱 Tool Set}
        ToolBox -->|解析批注与锚点| T1[parse_word_comments]
        ToolBox -->|读取特定章节段落| T2[read_section_content]
        ToolBox -->|定向重写小节| T3[rewrite_section_with_context]
        ToolBox -->|更新或重新生成图表| T4[regenerate_asset_bash]
        ToolBox -->|重排交叉引用与题注| T5[reindex_cross_references]
        
        T1 --> Observation[3. Observation: 观察工具执行结果]
        T2 --> Observation
        T3 --> Observation
        T4 --> Observation
        T5 --> Observation
        
        Observation --> CheckComplete{所有修改意见是否全部处理完成?}
        CheckComplete -->|未完成/需联动修改| Thought
    end
    
    CheckComplete -->|已全部完成| FinalAssembly[编译新版 Docx & 生成变更对比报告]
    FinalAssembly --> VersionCommit[版本库提交 commit_v1.1 & 更新 UI 数轴]
    VersionCommit --> ExportDone([导出: output/v1.1_批注修改版.docx + Changelog.md])
```

### 3.1 ReAct Agent 工具箱清单（Tool Registry）

| 工具名称 | 功能描述 | 输入参数 |
| :--- | :--- | :--- |
| `parse_word_comments` | 从上传的 docx 中解析导师批注、修订痕迹及被批注原文锚点 | `docx_path` |
| `read_section_content` | 读取指定章节（如“3.2 业务流程分析”）的当前正文与图表清单 | `section_id` |
| `rewrite_section_with_context` | 针对具体批注意见重写该小节，自动注入 `spec.json` 保持上下文一致 | `section_id`, `revision_instruction`, `context_summary` |
| `regenerate_asset_bash` | 通过 bash 执行 Python 或 Mermaid 脚本更新有变动的图表或 UI 截图 | `asset_id`, `new_script_source` |
| `reindex_cross_references` | 重新全量扫描全篇图表与文献序号，修复因增删造成的编号断裂 | `workspace_dir` |
| `generate_semantic_diff` | 比对旧版本与新版本，输出详细的《论文修改对照说明书 (Changelog)》 | `old_version_id`, `new_version_id` |

---

## 4. 关键设计共识沉淀（Design Alignment Summary）

通过深入讨论，本工作流确立了以下核心工程共识：

1. **唯一事实源前置硬编码**：在 `spec.json` 中完整锁定技术栈、系统模块、数据库 Schema（数据表字段字典），全流程只读引用，彻底消灭前后文矛盾。
2. **两阶段大纲规划**：先定 6~7 个大章宏观骨架，再微观展开 2~3 级小标题与图表埋点。
3. **二级小节顺序链撰写（~1,000字/次）**：全篇迭代 15~18 次，稳定产出 1.2w~1.5w 字的充实长文。
4. **即时资产先导（看图说话）**：写到插图小节时先通过 bash 生成真实图片，再将图片信息喂给 Prompt，图文天然紧密咬合。
5. **真实前端代码渲染 UI 截图**：预置精美 Tailwind 模板 + Playwright 本地无头截图，产出 1080P 高仿真软开界面图。
6. **轻量双轨滑动上下文**：仅传递 `spec.json` + 上节尾部 300 字与摘要 + 图表计数器，单次输入极小、速度极快、衔接自然。
7. **真实文献库与 GB/T 7714 动态对齐**：前置抓取 20~25 篇真实论文，按文中首次引用顺序动态排号并打上原生上标。
8. **极速单次放行**：创作模式追求最快速度，不设繁琐重试，留待编辑模式的 ReAct 循环进行增量微调。

