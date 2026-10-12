# 装配绑定

模板准备阶段提供绑定，装配阶段只能消费，不自行猜测原型或修改绑定。
`template_sha256` 对应批准的模板文件；正文锚点、段落原型均按直属 body 段落的完整文本唯一定位。
正文锚点和原型会被生成内容替换/移除，其他模板内容保留。原型不可含分节或域；原有书签随首次实例保留，重复实例不复制原有书签；新图表/文献使用独立书签；图片原型须恰含一张内嵌图及唯一识别文本。

```json
{
  "template_sha256": "模板文件 SHA256",
  "body_marker": "{{正文}}",
  "paragraphs": {
    "heading1": "{{一级标题原型}}",
    "heading2": "{{二级标题原型}}",
    "heading3": "{{三级标题原型}}",
    "body": "{{正文原型}}",
    "figure": "{{图片原型}}",
    "figure_caption": "{{图题原型}}",
    "table_caption": "{{表题原型}}",
    "bibliography_heading": "{{参考文献标题原型}}",
    "bibliography": "{{参考文献原型}}"
  },
  "tables": {"3": 0},
  "fields": {"{{论文题目}}": "topic", "{{摘要}}": "abstract", "{{关键词}}": "keywords"}
}
```

`tables` 的键是列数，值是模板直属 body 表格的零基索引。多行表格通常有三行原型：首行为表头，第二行为普通数据行，末行为最后数据行。两行普通网格表可重复使用数据行；含末行专用单元格底边框时仍需三行原型。列宽、单元格和三线表格式来自原型；不同列数需不同原型。段落原型只需提供实际会用到的类型，正文及所需标题层级必需。
图片默认采用 `image_sizing=fit_width`：复用模板图片段落、对齐和其他样式，以原型宽度及版心为上限，按素材实际比例调整宽高；高度最多占版心的90%，为图题留出空间。需要完全固定原型尺寸时，契约显式设置 `image_sizing=fixed`，编码素材必须匹配原型比例。新增媒体及关系不会更改已有媒体或关系。
元信息允许 topic/abstract/keywords，以及模板需要时的 topic_en/abstract_en/keywords_en/acknowledgements；可跨 run 替换，保留原字体和属性。摘要/关键词绑定必需。
输出只允许写入该任务 `assembly/`，校验报告证明受保护部件逐字节一致、分节属性一致与确定性重放一致。
原始模板及批准模板不覆盖；不通过 LibreOffice 回存最终 DOCX，避免格式漂移。PDF 是预览派生物。

排版覆盖规则：正文文献 REF 引用的显示 run 使用 `vertAlign=superscript`；文献条目复用 `body` 原型并设置 `outlineLvl=9`，不进入目录。图片段落强制 `spacing line=240 lineRule=auto` 并关闭网格吸附，避免模板固定行距裁切图片。`state.layout_options.chapter_page_break=true` 为各一级章标题设置 `pageBreakBefore`，CLI 可用 `--chapter-page-break` 开启；默认关闭以适配学校要求。上述为明确的局部排版覆盖，命名样式及原始模板保持不变。

离线修订使用 `agent.assembly.editorial.revise`，输入显式修订计划，在独立工作区保存新正文、图表数据、校验指纹及编辑记录，然后交由 AssemblyAgent 导出。禁止把编辑后的内容标记为旧语义审查已通过。可通过 `tests/完整工作流/revise_offline.py` 执行，全程禁网。

交付流程为 inspect → assemble → verify → check_assembly → render_and_finalize → verify。结构检查读取段落的直接与继承大纲级别，拒绝空标题和无正文、无有效子章节的空章节。没有内容的可选前言、附录自动移除，包括它们专属的空分节；保留节的页面设置、原始模板、命名样式不变。空段落不进入导航窗格。

目录从实际有效标题重建，清除旧缓存、旧点线制表位，生成带跳转书签和 PAGEREF 页码域的目录条目。采用固定书签目录而非保留学校模板的陈旧 TOC 域；增加或删除章节时重新装配目录，分页变化时可刷新页码域。本地 LibreOffice 排版后将实际页码缓存写回交付 DOCX，不能仅更新 PDF。finalize 校验每个页码、跳转目标、目录与正文标题一致性，且只修改目录页码缓存，不重写字体和样式。最终 PDF 检查空白页，失败则不标记交付成功。

本地排版依赖 `/usr/bin/python3` 的 UNO、LibreOffice Writer 和 Poppler 工具，失败会明确报错，不调用付费模型。原始确定性装配稿、最终含页码缓存的 DOCX、PDF 和校验报告分别保留。渲染结果的页码缓存绑定装配稿哈希，重放验证使用同一份经过实际排版的缓存。
