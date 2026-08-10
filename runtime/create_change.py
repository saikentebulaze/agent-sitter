from __future__ import annotations
import argparse, json, re
from pathlib import Path
from project_context import resolve_project_context

FILES=['change.yaml','proposal.md','design.md','tasks.md','verification.md','knowledge-sync.md','archive-summary.md']
CHANGE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('change_id')
    ap.add_argument('--title',required=True)
    ap.add_argument('--task-id',default='')
    ap.add_argument('--project', type=Path, default=Path.cwd())
    args=ap.parse_args()
    if not CHANGE_ID.fullmatch(args.change_id):
        raise SystemExit('change_id must contain only lowercase letters, digits, and hyphens')
    if args.task_id and not CHANGE_ID.fullmatch(args.task_id):
        raise SystemExit('task_id must contain only lowercase letters, digits, and hyphens')
    try:
        context = resolve_project_context(args.project)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    assets=context.adapter_root/'skills/change-governor/assets'
    target=(context.project_root/'changes/active'/args.change_id).resolve()
    active_root=(context.project_root/'changes/active').resolve()
    if target.parent != active_root:
        raise SystemExit('change_id resolves outside changes/active')
    if target.exists(): raise SystemExit(f'change exists: {target}')
    target.mkdir(parents=True)
    for name in FILES:
        src=assets/f'{name}.template'
        text=src.read_text(encoding='utf-8')
        if name=='change.yaml':
            text=text.replace('replace-with-change-id',args.change_id)
            text=text.replace('replace-with-title',json.dumps(args.title, ensure_ascii=False))
            if args.task_id:
                text=text.replace('source_task_id:\n',f'source_task_id: {json.dumps(args.task_id)}\n')
        (target/name).write_text(text,encoding='utf-8')
    print(target.relative_to(context.project_root))
if __name__=='__main__': main()
