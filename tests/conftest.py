"""每次自动回归按中文问题目录记录独立结果，禁用隐式真实 API 测试。"""
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path

RUN = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
REPORTS = defaultdict(list)


def pytest_runtest_logreport(report):
    if report.when == "call" or report.failed:
        file = Path(report.nodeid.split("::")[0])
        REPORTS[file.parent].append({"test": report.nodeid, "phase": report.when,
                                    "outcome":report.outcome, "duration":report.duration,
                                    "failure":str(report.longrepr) if report.failed else None})


def pytest_sessionfinish(session, exitstatus):
    for folder, results in REPORTS.items():
        output = folder/"runs"/(RUN+"_"+folder.name)
        output.mkdir(parents=True, exist_ok=True)
        (output/"result.json").write_text(json.dumps({"exit_status":int(exitstatus), "tests":results}, ensure_ascii=False, indent=2))
