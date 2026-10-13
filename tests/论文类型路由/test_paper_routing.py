"""Routing and evidence/outline contracts across disciplines; no live models."""
from copy import deepcopy
import json

import pytest
from langchain_core.messages import AIMessage

from agent.paper_routing import (agent_prompt, ensure_paper_profile, resolve_paper_profile,
                                 routing_context, PAPER_TYPES)
from agent.output_parsers.outline_parser import parse_outline_output
from agent.outline_agent import OutlineAgent
from agent.research import freeze_research, assert_research_lock
from agent.writing.storage import input_fingerprint
from agent.writing.tools import create_writing_tools


@pytest.mark.parametrize('topic,discipline,expected', [
    ('乡村旅游资源开发研究', '旅游管理', 'case_study'),
    ('基于协同过滤算法的推荐系统设计与实现', '计算机科学与技术', 'software'),
    ('基于Spring Boot的预约系统', '', 'software'),
    ('软件工程研究进展', '软件工程', 'review'),
    ('算法性能实验研究', '计算机科学与技术', 'experimental'),
    ('学习动机影响因素的实证研究', '教育学', 'empirical'),
    ('红楼梦的叙事研究', '汉语言文学', 'theoretical'),
    ('某企业转型案例研究', '工商管理', 'case_study'),
    ('未确定选题', '心理学', 'empirical'),
    ('未确定选题', '计算机科学与技术', 'general'),
    ('待定研究', '', 'general'),
])
def test_auto_route(topic, discipline, expected):
    state = {'topic': topic, 'discipline': discipline}
    before = deepcopy(state)
    assert resolve_paper_profile(state)['type'] == expected
    assert state == before


def test_explicit_type_and_domain_precedence():
    assert resolve_paper_profile({'topic': '待定', 'research_domain': '文本分析',
                                  'discipline': '软件工程'})['type'] == 'theoretical'
    assert resolve_paper_profile({'topic': '预约系统', 'paper_type': 'review'})['type'] == 'review'
    with pytest.raises(ValueError, match='不支持'):
        resolve_paper_profile({'paper_type': 'typo'})
    assert resolve_paper_profile({'single_source_of_truth': {'db_schemas': {'user': {}}}})['type'] == 'software'


def outline():
    def node(sid, title, words):
        return dict(section_id=sid, title=title, target_words=words, status='pending', planned_assets=[])
    return {'outline_plan': [node('1', '第一章 绪论', 0), node('1.1', '研究背景', 100),
                            node('2', '第二章 理论基础', 0), node('2.1', '核心概念', 100),
                            node('3', '第三章 案例分析', 0), node('3.1', '资源分析', 100)]}


def test_nonsoftware_outline_allows_two_levels_but_keeps_structure_validation():
    state = {'topic': '乡村旅游资源开发研究'}
    data = outline()
    assert parse_outline_output(json.dumps(data), state) == data
    broken = deepcopy(data)
    broken['outline_plan'][1]['section_id'] = '2.1.1'
    with pytest.raises(ValueError):
        parse_outline_output(json.dumps(broken), state)
    with pytest.raises(ValueError, match='三级'):
        parse_outline_output(json.dumps(data), {'topic': '预约系统设计与实现'})


def test_software_still_requires_er_and_each_database_table():
    data = outline()
    data['outline_plan'][2]['title'] = '第二章 相关理论与技术'
    data['outline_plan'][-1]['target_words'] = 0
    data['outline_plan'][-1]['title'] = '数据库设计'
    for sid, title, assets in [('3.1.1', '概念结构设计', ['fig_3_1 系统ER图']),
                               ('3.1.2', '逻辑结构设计', ['tbl_3_1 user 数据表结构三线表'])]:
        data['outline_plan'].append(dict(section_id=sid, title=title, target_words=100,
                                       status='pending', planned_assets=assets))
    state = {'topic': '预约系统', 'single_source_of_truth': {'db_schemas': {'user': {}}}}
    parse_outline_output(json.dumps(data), state)
    state['single_source_of_truth']['db_schemas']['booking'] = {}
    with pytest.raises(ValueError, match='booking'):
        parse_outline_output(json.dumps(data), state)
    del state['single_source_of_truth']['db_schemas']['booking']
    data['outline_plan'][-2]['planned_assets'] = []
    with pytest.raises(ValueError, match='ER'):
        parse_outline_output(json.dumps(data), state)


@pytest.mark.parametrize('kind', PAPER_TYPES)
def test_role_prompts_have_one_heading_and_flat_list(kind):
    for role in ('outline', 'writing', 'coding'):
        lines = agent_prompt(role, {'paper_type': kind}).splitlines()
        assert lines[0].startswith('# ')
        assert all(line.startswith('- ') for line in lines[2:])
        assert sum(line.startswith('#') for line in lines) == 1


def test_nonsoftware_agent_receives_matching_prompt_and_validation():
    class Model:
        def bind(self, **kwargs):
            return self
        def invoke(self, messages):
            assert '案例与应用研究' in messages[0].content
            assert json.loads(messages[1].content)['paper_profile']['type'] == 'case_study'
            return AIMessage(content=json.dumps(outline()))
    state = {'topic': '旅游资源开发研究', 'discipline': '旅游管理'}
    OutlineAgent(llm=Model()).invoke(state)
    assert state['outline_plan'] == outline()['outline_plan']


def test_profile_changes_invalidate_lock_and_writing_cache():
    state = {'topic': '乡村旅游研究', 'discipline': '旅游管理', 'outline_plan': outline()['outline_plan']}
    first = input_fingerprint(state)
    changed = {**state, 'paper_type': 'empirical'}
    assert first != input_fingerprint(changed)
    freeze_research(state)
    state['paper_type'] = 'empirical'
    with pytest.raises(ValueError, match='路由'):
        assert_research_lock(state)


def test_rule_file_change_invalidates_profile(tmp_path, monkeypatch):
    import agent.paper_routing as routing
    for source in routing.RULES_DIR.glob('*.json'):
        (tmp_path / source.name).write_bytes(source.read_bytes())
    monkeypatch.setattr(routing, 'RULES_DIR', tmp_path)
    state = {'topic': '旅游资源开发研究'}
    ensure_paper_profile(state)
    path = tmp_path / 'general.json'
    value = json.loads(path.read_text())
    value['writing'] += '\n新的约束。'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='规则配置'):
        resolve_paper_profile(state)


def test_asset_delegation_keeps_parent_profile(tmp_path):
    state = {'topic': '旅游资源开发研究', 'discipline': '旅游管理'}
    class Coder:
        def run_asset(self, task, workspace):
            assert resolve_paper_profile(task) == resolve_paper_profile(state)
            assert '案例与应用研究' in agent_prompt('coding', task)
            return {'asset_id': task['asset_id']}
    tools = create_writing_tools(str(tmp_path), tasks=[{'section_id': '3.1', 'planned_assets': ['tbl_3_1 案例表']}],
                                 coder=Coder(), paper_context=routing_context(state))
    tool = next(t for t in tools if t.name == 'code_asset')
    assert json.loads(tool.invoke({'section_id': '3.1', 'asset_id': 'tbl_3_1', 'instructions': '使用提供的案例资料'}))['asset_id'] == 'tbl_3_1'


def test_nonsoftware_full_workflow_and_resume(tmp_path):
    from tests.完整工作流.test_workflow import setup, Model, Literature
    from agent.workflow import PaperWorkflow
    from agent.writing import WritingAgent
    from pathlib import Path

    state, original_model, _, _ = setup(tmp_path)
    state.update(topic='乡村旅游资源开发研究', discipline='旅游管理',
                 single_source_of_truth={}, outline_plan=outline()['outline_plan'])

    class CaseModel(Model):
        prompts = []
        def invoke(self, messages):
            self.prompts.append(messages[0].content)
            context = json.loads(messages[1].content)
            if 'user_facts' in context:
                value = dict(research_object='乡村旅游资源', objectives=['分析开发条件'],
                             research_methods=['案例分析'], entities=[{'name': '旅游资源'}],
                             technical_design={}, evaluation_plan=['拟比较资源条件'], limitations=['尚无实地资料'])
            elif 'current_tasks' in context:
                self.writes += 1
                value = {'sections': [dict(section_id=t['section_id'], title=t['title'],
                    summary='乡村旅游资源分析方案', key_facts=['采用案例分析方法'], assets=[], citations=['ref1'],
                    content='本研究拟采用案例分析方法梳理乡村旅游资源的开发条件，围绕资料来源、资源特征与开发边界展开论证。'
                            '后续将依据可核验资料比较不同资源的适用条件，并说明研究限制。当前尚无实地调查证据，'
                            '因此仅提出研究方案，不宣称已取得经营成效。相关主题见[[REF_CITE:ref1]]。')
                    for t in context['current_tasks']]}
            elif 'research' in context:
                value = {'abstract': '本研究提出乡村旅游资源的案例分析方案，尚无实地资料。', 'keywords': ['乡村旅游', '案例分析']}
            else:
                return super().invoke(messages)
            return AIMessage(content=json.dumps(value, ensure_ascii=False))

    class CaseLiterature(Literature):
        def invoke(self, state):
            super().invoke(state)
            state['bib_pool'][0].update(title='乡村旅游研究（测试夹具）', query='乡村旅游')

    model = CaseModel(original_model.source)
    workflow = PaperWorkflow(llm=model, literature=CaseLiterature(),
                             writer=WritingAgent(llm=model, skills=[], max_repairs=0))
    result = workflow.invoke(state)
    assert result['paper_profile']['type'] == 'case_study'
    assert result['workflow_report']['status'] == 'completed'
    assert Path(result['final_doc_path']).is_file()
    assert all('系统' not in r['content'] for r in result['writing_records'])
    writes = model.writes
    workflow.invoke(state)
    assert model.writes == writes
    with pytest.raises(ValueError, match='不同输入'):
        workflow.invoke({**state, 'paper_type': 'empirical'})
