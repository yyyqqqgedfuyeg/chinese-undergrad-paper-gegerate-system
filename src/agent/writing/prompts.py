"""Compatibility export; runtime prompts are selected from versioned paper rules."""
from ..paper_routing import agent_prompt

WRITING_PROMPT = agent_prompt("writing", {"paper_type": "software"})
