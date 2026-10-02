"""python -m test.test_literature_agent_real：真实 .env 模型调用 + 全球学术接口。"""

import argparse
import copy
import json
import os
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

from agent import LiteratureAgent, create_initial_global_state
from agent.agent import BaseReActAgent
from agent.literature_tool import LiteratureSearcher
from agent.output_parsers import parse_literature_output


def run_test(publication_year_range=None):
    root = Path(__file__).resolve().parent.parent
    assert (root / ".env").is_file(), "缺少真实 .env"
    load_dotenv(root / ".env", override=True)
    assert os.getenv("DEEPSEEK_API_KEY", "").strip(), "缺少模型密钥"
    model_calls, searches = [], []

    def inspect_request(request):
        payload = json.loads(request.content)
        assert [t["function"]["name"] for t in payload["tools"]] == ["search_academic_literature"]
        model_calls.append({"model": payload["model"], "tools": ["search_academic_literature"]})
        print(f"真实模型请求 #{len(model_calls)}：仅挂载文献搜索工具", flush=True)

    def inspect_search(response):
        searches.append({"host": response.request.url.host, "status": response.status_code})
        print(f"学术接口 {response.request.url.host}: {response.status_code}", flush=True)

    state = create_initial_global_state(
        topic=os.getenv("LITERATURE_TEST_TOPIC", "基于 Spring Boot 和 Vue 的高校心理咨询预约系统的设计与实现"),
        single_source_of_truth={"tech_stack": {"backend": "Spring Boot 3", "frontend": "Vue 3"}},
        publication_year_range=publication_year_range,
    )
    before = copy.deepcopy(state)
    started = time.monotonic()
    with httpx.Client(event_hooks={"request": [inspect_request]}, timeout=180) as model_client, \
            httpx.Client(event_hooks={"response": [inspect_search]}, timeout=30, follow_redirects=True) as search_client:
        base = BaseReActAgent._create_default_llm(temperature=None)
        llm = type(base)(model=base.model_name, api_key=base.openai_api_key, base_url=base.openai_api_base,
                         temperature=None, http_client=model_client, timeout=180, max_retries=0)
        agent = LiteratureAgent(llm=llm, searcher=LiteratureSearcher(search_client))
        assert agent.invoke(state) is state
        parse_literature_output({"bib_pool": state["bib_pool"]}, require_complete=True)
        assert 1 <= len(model_calls) <= 4
        assert searches and all(p["source_url"] for p in state["bib_pool"])
        for key in before:
            if key != "bib_pool":
                assert state[key] == before[key], f"不应修改 {key}"
        # 独立按 ID 回查每一条，核对标题和出版年份，排除模型生成的条目。
        for paper in state["bib_pool"]:
            assert paper["formatted"] != paper["title"]
            assert paper["title"] in paper["formatted"]
            assert f"[{paper['document_type']}]" in paper["formatted"]
            assert paper["journal"] in paper["formatted"] and str(paper["year"]) in paper["formatted"]
            if publication_year_range:
                assert paper["year"] >= publication_year_range.get("start_year", 1500)
                assert paper["year"] <= publication_year_range.get("end_year", 2100)
            response = search_client.get(paper["source_url"])
            response.raise_for_status()
            raw = response.json()
            if paper["source"] == "openalex":
                assert raw["title"].strip() == paper["title"]
                assert raw["publication_year"] == paper["year"]
            else:
                assert raw["message"]["title"][0].strip() == paper["title"]
    report = {"result": "passed", "config_source": ".env", "model_calls": model_calls,
              "counts": {lang: sum(p["language"] == lang for p in state["bib_pool"]) for lang in ("zh", "en")},
              "individually_verified": len(state["bib_pool"]), "search_requests": searches,
              "duration_seconds": round(time.monotonic() - started, 2), "global_state": state}
    path = root / ("test/literature_agent_year_range_real.log" if publication_year_range
                   else "test/literature_agent_real.log")
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"真实 .env 测试通过：{report['counts']}，20 条逐一回查成功。记录：{path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int)
    parser.add_argument("--end-year", type=int)
    args = parser.parse_args()
    bounds = {key: value for key, value in vars(args).items() if value is not None}
    run_test(bounds or None)
