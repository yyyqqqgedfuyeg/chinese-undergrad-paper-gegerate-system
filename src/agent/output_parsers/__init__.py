"""按 agent 拆分的输出解析器；仅做结构解析和业务校验。"""

from .outline_parser import OutlineOutput, SectionPlanOutput, parse_outline_output

__all__ = ["OutlineOutput", "SectionPlanOutput", "parse_outline_output"]

from .literature_parser import LiteratureRecord, parse_literature_output

__all__ += ["LiteratureRecord", "parse_literature_output"]
