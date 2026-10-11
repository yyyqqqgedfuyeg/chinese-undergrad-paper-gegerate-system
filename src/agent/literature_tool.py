"""单一文献工具：全球 OpenAlex 检索，Crossref 补充；目标 15 中文 + 5 英文。"""

import hashlib
import os
import re
import time
from datetime import datetime, timezone
from itertools import zip_longest
from urllib.parse import quote

import httpx
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .output_parsers.literature_parser import LiteratureRecord, parse_literature_output, title_identity


class LiteratureSearchError(RuntimeError):
    """检索失败或真实结果不足；信息中不包含密钥或带鉴权参数的 URL。"""


class PublicationYearRange(BaseModel):
    """发表年份闭区间；允许仅指定起始或结束年份。"""
    model_config = ConfigDict(extra="forbid", strict=True)
    start_year: int | None = Field(default=None, ge=1500, le=2100)
    end_year: int | None = Field(default=None, ge=1500, le=2100)

    @model_validator(mode="after")
    def validate_order(self):
        if self.start_year is not None and self.end_year is not None and self.start_year > self.end_year:
            raise ValueError("start_year 不能晚于 end_year")
        return self

    def contains(self, year):
        return ((self.start_year is None or year >= self.start_year)
                and (self.end_year is None or year <= self.end_year))

    def api_filters(self, source):
        start_name, end_name = (("from_publication_date", "to_publication_date") if source == "openalex"
                                else ("from-pub-date", "until-pub-date"))
        return ([f"{start_name}:{self.start_year}-01-01"] if self.start_year is not None else []) + (
            [f"{end_name}:{self.end_year}-12-31"] if self.end_year is not None else [])


class SearchQueries(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chinese_queries: list[str] = Field(min_length=1, max_length=4,
        description="1-4 个中文关键词短语，覆盖题目核心主题及紧密相关方向，勿直接使用完整论文题目")
    english_queries: list[str] = Field(min_length=1, max_length=4,
        description="1-4 个相应的英文主题检索短语")
    publication_year_range: PublicationYearRange | None = Field(default=None,
        description="可选发表年份区间，start_year/end_year 均含边界；可仅填一端，省略则不限年份")

    @field_validator("chinese_queries", "english_queries")
    @classmethod
    def validate_queries(cls, values):
        if any(not value.strip() or len(value) > 160 for value in values):
            raise ValueError("检索词须为 1-160 个字符")
        return list(dict.fromkeys(value.strip() for value in values))


def _language(title, declared):
    declared = (declared or "").lower().replace("_", "-").split("-")[0]
    cjk = bool(re.search(r"[\u3400-\u9fff]", title))
    if re.search(r"[\u3040-\u30ff\uac00-\ud7af]", title):
        return None, None
    if declared in {"zh", "en"}:
        # 中英文元数据互相冲突时丢弃，不将英文标题翻译后充当中文论文。
        if (declared == "zh") != cjk:
            return None, None
        return declared, "provider"
    if declared:
        return None, None
    # 无语言字段时仅接收明确中文标题；拉丁字母无法可靠区分英语等语言。
    return ("zh", "title_script") if cjk else (None, None)


def _doi(value):
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value or "", flags=re.I).strip().lower()
    return value if re.match(r"^10\.\d{4,9}/\S+$", value) else None


def matches_query(title, query):
    """标题必须包含检索主题，避免全文中的边缘提及挤占配额。"""
    title = title.casefold()
    terms = re.findall(r"[\u3400-\u9fff]+|[a-z0-9]+", query.casefold())
    stopwords = {"a", "an", "the", "of", "for", "and", "in", "on", "with", "based"}
    terms = [term for term in terms if term not in stopwords]
    return bool(terms) and all(term in title for term in terms)


def normalize_record(raw, source, query):
    """缺少核心书目信息、撤稿或语言冲突的记录直接丢弃。"""
    if source == "openalex":
        if raw.get("is_retracted") or raw.get("type") not in {"article", "review", "dissertation"}:
            return None
        title = raw.get("title") or ""
        authors = ", ".join(a.get("author", {}).get("display_name", "")
                            for a in raw.get("authorships", []) if a.get("author", {}).get("display_name"))
        location = raw.get("primary_location") or {}
        document_type = ("D" if raw.get("type") == "dissertation" else
                         "C" if (location.get("source") or {}).get("type") == "conference" else "J")
        journal = (location.get("source") or {}).get("display_name") or ""
        year = raw.get("publication_year")
        doi = _doi(raw.get("doi"))
        source_id = raw.get("id") or ""
        source_url = source_id.replace("https://openalex.org/", "https://api.openalex.org/")
        url = ("https://doi.org/" + doi) if doi else location.get("landing_page_url") or source_id
        biblio = raw.get("biblio") or {}
        volume, issue = biblio.get("volume"), biblio.get("issue")
        pages = "-".join(str(p) for p in [biblio.get("first_page"), biblio.get("last_page")] if p)
    else:
        if raw.get("type") not in {"journal-article", "proceedings-article", "dissertation"}:
            return None
        if any(u.get("type") in {"retraction", "withdrawal"} for u in raw.get("update-to", [])):
            return None
        title = next(iter(raw.get("title") or []), "")
        document_type = {"journal-article": "J", "proceedings-article": "C", "dissertation": "D"}[raw["type"]]
        authors = ", ".join(" ".join(filter(None, [a.get("given"), a.get("family")]))
                            or a.get("name", "") for a in raw.get("author", []))
        journal = next(iter(raw.get("container-title") or []), "")
        dates = (raw.get("published") or raw.get("issued") or {}).get("date-parts") or [[]]
        year = dates[0][0] if dates[0] else None
        doi = _doi(raw.get("DOI"))
        if not doi:
            return None
        source_id = doi
        source_url = "https://api.crossref.org/works/" + quote(doi, safe="")
        url = "https://doi.org/" + doi
        volume, issue, pages = raw.get("volume"), raw.get("issue"), raw.get("page")
    language, basis = _language(title, raw.get("language"))
    identity = doi or source_id
    record = dict(key="cite_" + hashlib.sha256(identity.encode()).hexdigest()[:16],
                  title=title, authors=authors, journal=journal, year=year,
                  language=language, language_basis=basis, doi=doi, url=url,
                  source=source, source_id=source_id, source_url=source_url, query=query,
                  retrieved_at=datetime.now(timezone.utc).isoformat(),
                  document_type=document_type,
                  volume=str(volume or ""), issue=str(issue or ""), pages=str(pages or ""))
    try:
        return LiteratureRecord.model_validate(record).model_dump()
    except ValidationError:
        return None


class LiteratureSearcher:
    def __init__(self, client=None):
        self.client = client

    @staticmethod
    def _get(client, url, params, headers):
        for attempt in range(3):
            try:
                response = client.get(url, params=params, headers=headers)
                if response.status_code == 429 or response.status_code >= 500:
                    if attempt < 2:
                        retry_after = response.headers.get("Retry-After", "")
                        time.sleep(min(float(retry_after), 5) if retry_after.isdigit() else 0.5 * 2 ** attempt)
                        continue
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                raise LiteratureSearchError(f"HTTP {exc.response.status_code}") from None
            except httpx.TransportError:
                if attempt == 2:
                    raise LiteratureSearchError("网络连接失败或超时") from None
                time.sleep(0.5 * 2 ** attempt)
            except ValueError:
                raise LiteratureSearchError("检索服务返回非 JSON 响应") from None

    def search(self, chinese_queries, english_queries, publication_year_range=None):
        queries = SearchQueries(chinese_queries=chinese_queries, english_queries=english_queries,
                                publication_year_range=publication_year_range)
        if self.client is not None:
            return self._search(self.client, queries)
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            return self._search(client, queries)

    def _search(self, client, queries):
        selected, seen_dois, seen_titles = {"zh": [], "en": []}, set(), set()
        diagnostics = []
        for language, terms, quota in [("zh", queries.chinese_queries, 15), ("en", queries.english_queries, 5)]:
            for source in ("openalex", "crossref"):
                batches = []
                for query in terms:
                    headers = {"User-Agent": "UndergradLiteratureAgent/1.0"}
                    if source == "openalex":
                        url = "https://api.openalex.org/works"
                        # 查询值只保留词语，避免 OpenAlex 过滤器分隔符改变检索语义。
                        title_query = " ".join(re.findall(r"[\w]+", query, flags=re.UNICODE))
                        params = {"filter": f"language:{language},is_retracted:false,title.search:{title_query}",
                                  "per-page": 50}
                        if os.getenv("OPENALEX_API_KEY"):
                            headers["Authorization"] = "Bearer " + os.environ["OPENALEX_API_KEY"]
                    else:
                        url = "https://api.crossref.org/works"
                        params = {"query.bibliographic": query, "rows": 50, "sort": "relevance"}
                        if os.getenv("CROSSREF_MAILTO"):
                            params["mailto"] = os.environ["CROSSREF_MAILTO"]
                    if queries.publication_year_range is not None:
                        filters = queries.publication_year_range.api_filters(source)
                        if filters:
                            params["filter"] = ",".join(filter(None, [params.get("filter"), *filters]))
                    try:
                        data = self._get(client, url, params, headers)
                        items = data["results"] if source == "openalex" else data["message"]["items"]
                        batch = [normalize_record(item, source, query) for item in items]
                        batches.append([p for p in batch if p and p["language"] == language
                                        and matches_query(p["title"], query)
                                        and (queries.publication_year_range is None
                                             or queries.publication_year_range.contains(p["year"]))])
                        diagnostics.append({"source": source, "query": query, "language": language,
                                            "candidates": len(batches[-1])})
                    except (LiteratureSearchError, KeyError, TypeError):
                        diagnostics.append({"source": source, "query": query, "language": language,
                                            "error": "source_unavailable_or_invalid_response"})
                # 按各检索词的相关性排名轮流选取，避免第一个关键词占满配额。
                for row in zip_longest(*batches):
                    for paper in row:
                        if paper is None or len(selected[language]) >= quota:
                            continue
                        title_key = title_identity(paper["title"])
                        if paper["doi"] in seen_dois or title_key in seen_titles:
                            continue
                        selected[language].append(paper)
                        if paper["doi"]:
                            seen_dois.add(paper["doi"])
                        seen_titles.add(title_key)
                if len(selected[language]) == quota:
                    break
        counts = {lang: len(items) for lang, items in selected.items()}
        return {**parse_literature_output({"bib_pool": selected["zh"] + selected["en"]}),
                "counts": counts, "searches": diagnostics,
                "publication_year_range": queries.publication_year_range.model_dump(exclude_none=True)
                    if queries.publication_year_range is not None else None,
                "complete": counts == {"zh": 15, "en": 5}}


def create_literature_tool(searcher=None):
    searcher = searcher if searcher is not None else LiteratureSearcher()
    return StructuredTool.from_function(
        func=searcher.search, name="search_academic_literature", args_schema=SearchQueries,
        description="全球真实学术文献检索。输入中文和英文主题关键词列表；通过 OpenAlex 和 Crossref，"
                    "可用 publication_year_range 限定发表年份（含边界）。"
                    "每条结果的 formatted 字段包含 GB/T 7714 风格参考文献写法。"
                    "去重后返回最多 15 篇中文和 5 篇英文的可追溯元数据。不足时返回已有结果和缺口，禁止编造。",
    )


search_academic_literature = create_literature_tool()
