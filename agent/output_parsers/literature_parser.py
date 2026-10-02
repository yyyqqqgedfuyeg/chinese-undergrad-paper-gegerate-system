"""文献池校验：只接收检索工具产生的元数据，不解析模型编造的参考文献。"""

import re
import unicodedata
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def title_identity(title: str) -> str:
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", title).casefold())


class LiteratureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    key: str = Field(min_length=1)
    title: str = Field(min_length=1)
    authors: str = Field(min_length=1)
    journal: str = Field(min_length=1)
    year: int = Field(ge=1500, le=2100)
    language: Literal["zh", "en"]
    language_basis: Literal["provider", "title_script"]
    doi: str | None
    url: str = Field(pattern=r"^https?://")
    source: Literal["openalex", "crossref"]
    source_id: str = Field(min_length=1)
    source_url: str = Field(pattern=r"^https://")
    query: str = Field(min_length=1)
    retrieved_at: str = Field(min_length=1)
    volume: str = ""
    issue: str = ""
    pages: str = ""
    document_type: Literal["J", "C", "D"] = "J"
    formatted: str = ""

    @model_validator(mode="after")
    def build_formatted_reference(self):
        """依据已有元数据生成 GB/T 7714 风格条目；不编造缺失出版信息。"""
        authors = [name.strip() for name in self.authors.split(",") if name.strip()]
        author_text = ", ".join(authors[:3])
        if len(authors) > 3:
            author_text += ", 等" if self.language == "zh" else ", et al"
        separator = "//" if self.document_type == "C" else ". "
        citation = f"{author_text}. {self.title}[{self.document_type}]{separator}{self.journal}, {self.year}"
        if self.volume:
            citation += f", {self.volume}"
        if self.issue:
            citation += f"({self.issue})"
        if self.pages:
            citation += f": {self.pages}"
        citation += "."
        if self.doi:
            citation += f" DOI:{self.doi}."
        # 不带序号，正文首次引用排序后再由装配节点统一编号。
        self.formatted = citation
        return self


def parse_literature_output(output: dict, *, require_complete: bool = False) -> dict:
    records = [LiteratureRecord.model_validate(item).model_dump() for item in output["bib_pool"]]
    counts = Counter(item["language"] for item in records)
    if counts["zh"] > 15 or counts["en"] > 5:
        raise ValueError("文献池超过 15 中文 + 5 英文上限")
    if require_complete and counts != {"zh": 15, "en": 5}:
        raise ValueError("文献池必须恰好包含 15 篇中文和 5 篇英文文献")
    for field in ("key", "doi", "title"):
        values = [title_identity(item[field]) if field == "title" else item[field].casefold()
                  for item in records if item[field]]
        if len(values) != len(set(values)):
            raise ValueError(f"文献池存在重复 {field}")
    return {"bib_pool": records}
