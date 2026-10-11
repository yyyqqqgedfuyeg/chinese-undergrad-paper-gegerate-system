"""Export a real template agent JSONL trace as a readable operation log.

.venv/bin/python test/export_template_agent_log.py <run-dir>
Only observable messages, decisions/evidence, calls and results are included.
"""
import argparse
import json
from pathlib import Path


def export(out):
    out = Path(out)
    rows = [json.loads(s) for s in (out/'agent-events.jsonl').read_text().splitlines()]
    lines = ['DOCX 模板 Agent 操作记录', '记录模型公开回复、工具决策/参数/返回及清洗依据；不包含隐藏推理。', '']
    calls = []
    usage = {'input_tokens':0,'output_tokens':0,'total_tokens':0}
    for row in rows:
        kind,data = row['kind'],row['data']
        if kind in ('run_start','run_complete','run_error','run_interrupted','completion_condition_met'):
            lines.extend([f"[{row['time']}] {kind}",json.dumps(data,ensure_ascii=False,indent=2),''])
        elif kind == 'task':
            lines.extend(['测试任务：',str(data),''])
        elif kind == 'message':
            if data['type'] == 'ai':
                for k in usage:
                    usage[k] += (data.get('usage') or {}).get(k,0)
                if data.get('content'):
                    lines.extend(['Agent 公开回复：',str(data['content']),''])
                for call in data.get('tool_calls',[]):
                    calls.append({'step':len(calls)+1,'time':row['time'],'name':call['name'],'args':call['args']})
                    lines.extend([f"步骤 {len(calls)} [{row['time']}] 调用 {call['name']}",json.dumps(call['args'],ensure_ascii=False,indent=2),''])
            elif data['type'] == 'tool':
                lines.extend([f"工具结果 [{row['time']}] {data.get('name')}",str(data['content']),''])
    plan_path = out/('references-plan.json' if (out/'references-plan.json').exists() else 'cleaning-plan.json')
    plan = json.loads(plan_path.read_text()) if plan_path.exists() else {}
    lines.extend(['计划中的证据、样式与操作：',json.dumps(plan,ensure_ascii=False,indent=2)])
    (out/'agent-operations.txt').write_text('\n'.join(lines)+'\n')
    summary = {'tool_call_count':len(calls),'tools':{name:sum(c['name']==name for c in calls) for name in sorted(set(c['name'] for c in calls))},'usage':usage,'operation_log':'agent-operations.txt','raw_log':'agent-events.jsonl','plan':plan_path.name if plan else None,'terminal_events':[r for r in rows if r['kind'] in ('run_complete','run_error','run_interrupted')]}
    (out/'operation-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(summary,ensure_ascii=False))


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('out')
    export(p.parse_args().out)
