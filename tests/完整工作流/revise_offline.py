"""Apply explicit local edits and assemble without any network access."""
import argparse
import json
from pathlib import Path
import socket
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('plan', type=Path)
    args = parser.parse_args()
    def no_network(*a, **kw):
        raise RuntimeError('Offline revision forbids network access')
    socket.socket.connect = no_network
    socket.socket.connect_ex = no_network
    socket.create_connection = no_network
    from agent.assembly.editorial import revise
    from agent.assembly import AssemblyAgent
    source = args.source.resolve()
    state = json.loads((source/'workspace/workflow/state.json').read_text())['state']
    manifest = json.loads((source/'workspace/writing/manifest.json').read_text())
    plan = json.loads(args.plan.read_text())
    state = revise(state, manifest, args.destination.resolve()/'workspace', plan)
    metadata = json.loads((source/'offline-metadata.json').read_text())
    state.update(metadata)
    report = AssemblyAgent(state, state['assembly_contract'], state['abstract'], state['keywords'],
                           str(Path(state['workspace_dir'])/'assembly/final.docx')).invoke()
    report.update(model_api_calls=0, editorial_plan=str(args.plan.resolve()), image_semantic_review_complete=False)
    (Path(state['workspace_dir'])/'assembly/revision-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False))
if __name__ == '__main__':
    main()
