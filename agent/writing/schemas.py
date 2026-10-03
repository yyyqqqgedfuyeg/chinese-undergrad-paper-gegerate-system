"""撰写结果与接力记录。完整正文保存在记录中，提示词使用摘要和路径按需读取。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class WritingAsset(StrictModel):
    asset_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    kind: Literal["diagram", "ui", "table"]
    source_path: str = Field(min_length=1, description="绘图代码、HTML 或表格数据的工作区相对路径")
    path: str = Field(min_length=1, description="实际导出图片或表格的工作区相对路径")


class SectionDraft(StrictModel):
    section_id: str = Field(pattern=r"^[1-9]\d*(?:\.[1-9]\d*){0,2}$")
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=1200)
    content: str = Field(min_length=1, description="不含本节标题的完整 Markdown 正文")
    key_facts: list[str] = Field(description="本节明确使用的术语、业务规则和关键论述")
    assets: list[WritingAsset]
    citations: list[str] = Field(description="正文实际使用的 bib_pool key")


class BatchOutput(StrictModel):
    sections: list[SectionDraft] = Field(min_length=1)


class WritingRecord(SectionDraft):
    content_path: str
    content_sha256: str
    node_index: int = Field(ge=1)


def handoff_context(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """保留所有历史条目的摘要、关键事实与路径，完整正文可用 read 获取。"""
    return [{key: value for key, value in record.items()
             if key not in {"content", "content_sha256"}} for record in records]
