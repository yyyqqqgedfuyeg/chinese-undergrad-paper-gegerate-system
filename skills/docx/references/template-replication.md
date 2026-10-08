# 从学校模板提取可复用文档

提供学校 DOCX 时，以该文件和其中明确的格式说明为依据。不要套用通用毕业论文参数。先提取旧样式的完整格式，在干净模板中清空旧样式定义，再新增并应用中文命名样式。先读取模板中的文本、分节、页眉页脚、字体、图表和域。`python` 应使用工作区 `.venv/bin/python`。

## 交付物与流程

1. `inspect` 保存完整样式 XML、字体表、主题、原始段落/run 属性、分节和部件校验和；`summary.json` 是给 agent 阅读的精简清单。完整数据在 `inventory.json`，不要仅依据样式名称推断直接格式。
2. agent 编写 `cleaning-plan.json`：标识说明文字和示例内容，替换为 `{{字段名}}`，保留声明正文、栏目名称、编号、分页、图表和域。每个修改提供原文和依据。学校模板的重复题目需包含页眉题目，填写示例值应与封面/中文论文题目保持一致。文字说明与现有格式冲突时，复刻版保留原格式；干净版遵循明确文字说明并记录冲突。未说明的参数继承源文档，不臆造字号/缩进。
3. 在计划添加 `style_rebuild`（见下节），`build` 先解析原样式的继承/直接格式，再删除原 styles.xml 的全部 style 定义和潜在内置样式条目，创建新的中文命名样式。所有新样式设置 customStyle、qFormat 和 uiPriority，出现在 Word 样式库中，并实际绑定到相应段落；表格样式也重新命名。匹配样式的直接属性移入定义，保留混合文字的格式差异。源文件和 replica.docx 保留全部原样式供追溯。输出 style-catalog.json 记录删除列表、新样式格式和应用次数。
4. `verify` 比较复刻版全部 ZIP 部件、干净版受保护结构、清洗计划和说明残留，同时检查原样式已删除、新样式可见且已应用、没有悬空样式引用。保存结果，有错误应修复计划并重试。流水线 verify 通过且 fill 成功后汇报产物、冲突和限制即可；外层已负责独立断言/XSD/渲染时，不另外开发一套重复检查脚本或提前读取尚在生成的验收文件。文件存在、命令返回 0 不能单独证明格式合规。
5. `fill` 同时处理正文、表格、页眉页脚，用占位符字典生成示例 DOCX，跨 run 替换且保留格式。渲染源文档、复刻版、干净版和填写示例，比较源文档与复刻版逐页像素并检查干净版布局。字体缺失/替代必须在报告中列出；不得将替代字体渲染声称为 Word 原字体像素完全一致。

命令（路径均相对项目根目录）：

```bash
.venv/bin/python skills/docx/scripts/template_pipeline.py inspect --source '学校模板.docx' --out test/template-run/source
.venv/bin/python skills/docx/scripts/template_pipeline.py build --source '学校模板.docx' --out test/template-run --plan test/template-run/cleaning-plan.json
.venv/bin/python skills/docx/scripts/template_pipeline.py verify --source '学校模板.docx' --out test/template-run --plan test/template-run/cleaning-plan.json
.venv/bin/python skills/docx/scripts/template_pipeline.py fill --template test/template-run/clean-template.docx --values test/template-run/values.json --output test/template-run/filled-demo.docx
```

## 计划 schema

```json
{
  "source_sha256": "从 summary.json 取得",
  "conflicts": [{"paragraph": 0, "observed": "现有格式", "required": "文字说明", "decision": "采用的格式及原因"}],
  "edits": [{
    "paragraph": 0,
    "expected_text": "完整原文，包含空格",
    "evidence": "为何清理/修正；对应源模板说明",
    "replacements": [{"old": "唯一匹配的原文片段", "new": "{{标题}}", "run_properties": {"rFonts": {"ascii": "黑体", "hAnsi": "黑体", "eastAsia": "黑体"}, "sz": {"val": "32"}, "color": {"val": "000000"}}}],
    "paragraph_properties": {"spacing": {"line": "360", "lineRule": "auto"}}
  }]
}
```

`part` 默认是 `word/document.xml`，也可指定 summary 的 stories 中存在的页眉/页脚部件；它们的段落索引是该部件全部 w:p 的顺序。`paragraph` 对于正文是直接隶属 body 的段落索引（含空段落，不含表格内段落），来自 summary。表内示例文本使用 `scope: "table"`，索引来自 `table_paragraphs`；默认 `scope: "body"`。表格几何与边框必须保留。一个段落一个 edit；多个 replacements 顺序执行，`old` 必须在当时文本中恰好出现一次，可跨 run。可先删除说明，再替换星号/叉号。属性名是 OOXML 名，数值为原始单位：字号半磅，间距 twips，auto 行距 240=1 倍、360=1.5 倍。未修改的同名属性在覆盖该属性节点时需一并写回，例如 spacing 的 before/after。

正文说明是 12pt 宋体、1.5 倍时，只修正内容 run 的字号/字体和段落行距；摘要/关键词的标签 run 可保留原格式。参考文献至少 15 篇、英文至少 1 篇，关键词至少 5 个等要求保存到计划的 `content_requirements`，不伪造内容来充数。目录可能只是静态示例或域缓存：保留原始域，填写后需要在 Word/排版程序中更新目录；不能将缓存页码当作最终页码验收。

模板含字符/行网格时，填写英文长文本后检查换行和右边界。英文摘要/关键词若出现字间距异常或越界，可在对应段落显式设置 `snapToGrid: {"val":"0"}`，保留分节网格定义，并记录以 12pt、1.5 倍自然排版为依据的冲突决策；不要靠缩短示例隐藏问题。

字体样式存储是样式 XML、字体名称/主题和段落直接属性，不等于字体文件打包。复杂样式切换属性、主题字体、字符/段落样式继承需结合原始 XML 和实际渲染判断。

## 清空预设并新增可见样式（新模板必须使用）

`style_rebuild` 是清洗计划的顶层字段。模式为 `replace_all`，不得通过给旧样式改名充当清理。`styles` 中每个定义提供新的稳定 ASCII id、中文显示名和清洗后的代表段落。默认选择代表段落中包含占位符的 run 提取字体，否则选择首个非空 run；也可以指定 sample_run。不要把模板内容写死在引擎里。

```json
{
  "style_rebuild": {
    "mode": "replace_all",
    "default_style": "PaperLayout",
    "styles": [
      {"id":"PaperLayout", "name":"论文空白段落", "sample":{"paragraph":2}, "paragraph_properties":{"outlineLvl":{"val":"9"}}},
      {"id":"PaperBody", "name":"论文正文", "sample":{"paragraph":88}, "paragraph_properties":{"outlineLvl":{"val":"9"}}},
      {"id":"PaperHeading1", "name":"论文一级标题", "sample":{"paragraph":91}, "paragraph_properties":{"outlineLvl":{"val":"0"}}}
    ],
    "assignments": [
      {"style":"PaperBody", "paragraphs":[88,92,94,97]},
      {"style":"PaperHeading1", "paragraphs":[91]}
    ]
  }
}
```

以上索引仅说明附件9的 schema，实际任务从 inspect 取得对应位置。还需定义并应用二/三级标题、封面、摘要/关键词、目录、图表题、参考文献、致谢、附录、表格文字、页眉/页脚等实际使用的样式。`sample` 和 assignments 可带 `part` / `scope`，规则与 edits 相同；assignments 使用 paragraphs 数组。每个新段落样式至少应用一次，未分配段落使用 default_style。一级/二级/三级标题 outlineLvl 为 0/1/2，正文为 9，避免旧标题层级污染正文。可选 paragraph_properties / run_properties 显式覆盖提取值；其它参数沿用学校模板。

Word/WPS 可能在打开时重新提供程序内置样式；验收检查保存的 DOCX 已清除所有旧定义和内置样式库条目，新增样式具有显示标记且正文实际使用它们，不承诺删除 Word 程序自身内置功能。
