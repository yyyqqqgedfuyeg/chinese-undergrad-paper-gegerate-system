"""大纲 agent 输出结构与解析：JSON 包装、目录层级及数据库资产校验。

只返回经过校验的 state 更新字典，不调用模型、不修改输入 state。
"""

import re
from typing import Any, Dict, Literal, Union

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..state import PaperGlobalState


class SectionPlanOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    section_id: str = Field(pattern=r"^[1-9]\d*(?:\.[1-9]\d*){0,2}$")
    title: str = Field(min_length=1, pattern=r"\S")
    target_words: int = Field(ge=0)
    status: Literal["pending"]
    planned_assets: list[str]


class OutlineOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    outline_plan: list[SectionPlanOutput] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_section_order(self):
        ids = [tuple(map(int, section.section_id.split("."))) for section in self.outline_plan]
        if len(set(ids)) != len(ids) or ids != sorted(ids):
            raise ValueError("section_id 必须唯一且按章节数字升序排列")
        id_set = set(ids)
        if ids[0] != (1,):
            raise ValueError("大纲必须从第一章标题（section_id=1）开始")
        for section, section_id in zip(self.outline_plan, ids):
            if len(section_id) > 1 and section_id[:-1] not in id_set:
                raise ValueError("每个小节必须先提供所属章标题和二级标题")
            if len(section_id) == 3 and section_id[0] <= 2:
                raise ValueError("第一、二章保留到二级标题")
            children = [key for key in ids if len(key) == len(section_id) + 1 and key[:-1] == section_id]
            if children and section.target_words != 0:
                raise ValueError("包含子标题的节点 target_words 必须为 0，避免重复计算字数")
            if not children and (len(section_id) == 1 or section.target_words <= 0):
                raise ValueError("每章需要小节，叶子小节 target_words 必须为正整数")
            if len(section_id) == 1 and section_id[0] > 2 and re.search(
                r"需求分析|系统分析|系统设计|总体设计|详细设计|数据库设计|系统实现|系统开发|系统测试", section.title
            ) and not any(len(key) == 3 and key[0] == section_id[0] for key in ids):
                raise ValueError("系统分析、设计、实现、测试等核心章节必须细分至三级标题")
        if any(not asset.strip() for section in self.outline_plan for asset in section.planned_assets):
            raise ValueError("planned_assets 不得包含空白条目")
        return self


def parse_outline_output(
    output: Union[str, BaseMessage], state: PaperGlobalState,
) -> Dict[str, Any]:
    """解析模型消息或 JSON 文本，返回 {"outline_plan": [...]}。

    state 中的 topic 与 single_source_of_truth 用于验证软件系统数据库资产。
    兼容 JSON 代码块包装，拒绝额外正文、损坏的 JSON、工具调用与不合规规划。
    """
    if not isinstance(output, (str, BaseMessage)):
        raise TypeError("大纲输出必须是 JSON 文本或模型消息")
    if getattr(output, "tool_calls", None) or getattr(output, "invalid_tool_calls", None):
        raise ValueError("大纲 agent 不允许工具调用")
    content = output if isinstance(output, str) else output.content
    if not isinstance(content, str):
        raise TypeError("大纲输出必须是 JSON 文本或包含 JSON 文本的模型消息")
    content = content.strip()
    # 部分兼容接口即使启用 JSON mode 仍附加代码块标记。
    # 仅去除外层包装，内部 JSON 完整性与数据结构仍由 Pydantic 严格校验。
    if content.startswith("```json\n") or content.startswith("```\n"):
        content = content.split("\n", 1)[1].strip()
        if content.endswith("```"):
            content = content[:-3].strip()
    outline = OutlineOutput.model_validate_json(content)
    facts = state.get("single_source_of_truth", {})
    software_system = bool(facts.get("tech_stack") or facts.get("db_schemas")) or bool(re.search(
        r"软件|开发|管理系统|预约系统|Spring|Vue|Django|Flask|小程序|APP", state["topic"], re.IGNORECASE
    ))
    if software_system:
        sections = {section.section_id: section for section in outline.outline_plan}
        database_leaves = []
        for section in outline.outline_plan:
            parts = section.section_id.split(".")
            if len(parts) == 3 and any(re.search(
                r"数据库|数据表|概念结构|逻辑结构|实体.*关系",
                sections[".".join(parts[:depth])].title,
            ) for depth in range(1, 4)):
                database_leaves.append(section)
        assets = [asset for section in database_leaves for asset in section.planned_assets]
        if not any(re.search(r"(?<![A-Za-z])E\s*[-－]?\s*R(?![A-Za-z])|实体.*关系", asset, re.IGNORECASE) for asset in assets):
            raise ValueError("软件系统的数据库三级小节必须规划 ER 图")
        tables = [asset for asset in assets if re.search(r"数据表|表结构|数据库表", asset)]
        if not tables:
            raise ValueError("软件系统的数据库三级小节必须规划数据表结构三线表")
        for table_name in facts.get("db_schemas", {}):
            if not any(table_name in asset for asset in tables):
                raise ValueError(f"缺少事实源数据表 {table_name} 的结构表规划")
    return outline.model_dump()
