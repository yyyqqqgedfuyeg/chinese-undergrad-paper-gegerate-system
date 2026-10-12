"""Resolve one versioned paper profile for generation, validation and resume."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

RULES_DIR = Path(__file__).with_name('paper_rules')
PAPER_TYPES = ('software', 'empirical', 'experimental', 'theoretical', 'case_study', 'review', 'general')


def _read(name):
    return json.loads((RULES_DIR / name).read_text(encoding='utf-8'))


def resolve_paper_profile(state):
    """Explicit type > topic/domain evidence > discipline > general fallback.

    Never classify on the bare word 开发 or on a computing major alone.
    Persisted profiles are checked against current inputs and rule contents.
    """
    catalog = _read('profiles.json')
    profiles = catalog['profiles']
    fields = {key: state.get(key) or '' for key in ('discipline', 'research_domain', 'paper_type')}
    if any(not isinstance(value, str) for value in fields.values()):
        raise ValueError('discipline、research_domain、paper_type 必须为字符串')
    fields = {key: value.strip() for key, value in fields.items()}
    requested = fields['paper_type']
    if requested and requested != 'auto' and requested not in profiles:
        raise ValueError(f'不支持的论文类型：{requested}；可选 auto 或 {", ".join(PAPER_TYPES)}')
    facts = state.get('single_source_of_truth', {})
    selected, reason = 'general', '未匹配明确类型，使用通用研究规则'
    if requested and requested != 'auto':
        selected, reason = requested, '用户显式指定论文类型'
    else:
        # Method-specific titles outrank broad subject words, e.g. software literature review.
        topic = state.get('topic', '')
        domain = fields['research_domain']
        for text, source in ((topic, '题目'), (domain, '研究领域')):
            for kind in ('review', 'empirical', 'software', 'experimental', 'theoretical', 'case_study'):
                if re.search(profiles[kind]['pattern'], text):
                    selected, reason = kind, f'{source}匹配{profiles[kind]["label"]}'
                    break
            if selected != 'general':
                break
        if selected == 'general' and (facts.get('db_schemas') or facts.get('tech_stack')):
            selected, reason = 'software', '已有技术栈或数据库事实，兼容软件论文输入'
        if selected == 'general':
            for kind, rule in profiles.items():
                if any(word in fields['discipline'] for word in rule['disciplines']):
                    selected, reason = kind, f'专业匹配{rule["label"]}'
                    break
    rules = profiles[selected]
    prompts = _read('software.json' if selected == 'software' else 'general.json')
    digest = hashlib.sha256(json.dumps({'catalog': catalog, 'prompts': prompts}, ensure_ascii=False,
                                       sort_keys=True).encode()).hexdigest()
    result = {'version': catalog['version'], 'rules_sha256': digest, 'type': selected,
              'discipline': fields['discipline'], 'research_domain': fields['research_domain'],
              'reason': reason, 'label': rules['label'], 'structure': rules['structure'],
              'rules': deepcopy(rules['rules'])}
    existing = state.get('paper_profile')
    if existing is not None and existing != result:
        raise ValueError('论文路由或规则配置发生变化，请使用原始输入或新建工作区')
    return result


def ensure_paper_profile(state):
    state['paper_profile'] = resolve_paper_profile(state)
    return state['paper_profile']


def is_software(state):
    return resolve_paper_profile(state)['type'] == 'software'


def profile_guidance(state):
    profile = resolve_paper_profile(state)
    return '\n'.join([
        f'论文类型：{profile["label"]}；专业：{profile["discipline"] or "未指定"}；研究领域：{profile["research_domain"] or "未指定"}。',
        f'章节结构参考：{profile["structure"]}。', *profile['rules'],
        '不同学科均须区分用户证据与拟议方案，不伪造数据、文献、访谈、实验或完成状态。',
    ])


def format_prompt(title, *parts):
    """Render one heading and a flat list; preserve literal JSON and all rules."""
    lines = []
    for part in parts:
        for line in part.splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            line = re.sub(r'^[-*]\s+', '', line)
            # Existing outline instructions are one long paragraph.
            lines.extend(s.strip() for s in re.split(r'(?<=。)', line) if s.strip())
    return f'# {title}\n\n' + '\n'.join('- ' + line for line in dict.fromkeys(lines))


def agent_prompt(role, state):
    profile = resolve_paper_profile(state)
    prompts = _read('software.json' if profile['type'] == 'software' else 'general.json')
    return format_prompt({'outline': '论文大纲规划', 'writing': '论文正文撰写', 'coding': '论文图表生成'}[role],
                         prompts[role], profile_guidance(state))


def routing_context(state):
    return {**{key: state.get(key, '') for key in ('topic', 'discipline', 'research_domain', 'paper_type')},
            'paper_profile': resolve_paper_profile(state)}
