"""项目资源与任务目录分离。"""
from pathlib import Path
import os


def project_root() -> Path:
    explicit = os.environ.get("PAPER_PROJECT_ROOT")
    if explicit:
        return Path(explicit).resolve(strict=True)
    for parent in Path(__file__).resolve().parents:
        if (parent / "skills/docx/SKILL.md").is_file():
            return parent
    raise RuntimeError("找不到项目资源；请设置 PAPER_PROJECT_ROOT")
