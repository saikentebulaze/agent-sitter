from __future__ import annotations
import argparse, shutil, subprocess, sys
from pathlib import Path
from project_context import resolve_project_context

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('change',type=Path); ap.add_argument('--dry-run',action='store_true'); ap.add_argument('--project', type=Path, default=Path.cwd()); args=ap.parse_args()
    try:
        context = resolve_project_context(args.project)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    source=args.change.resolve()
    active_root=(context.project_root/'changes/active').resolve()
    if source.parent != active_root:
        raise SystemExit('change must be a direct child of changes/active')
    if not source.is_dir():
        raise SystemExit(f'change directory not found: {source}')
    cmd=[sys.executable,str(context.package_root/'runtime/validate_change.py'),str(source)]
    r=subprocess.run(cmd,cwd=context.project_root)
    if r.returncode: raise SystemExit(r.returncode)
    target=context.project_root/'changes/archive'/source.name
    if target.exists(): raise SystemExit(f'archive target exists: {target}')
    print(f'{source} -> {target}')
    if not args.dry_run:
        target.parent.mkdir(parents=True,exist_ok=True); shutil.move(str(source),str(target)); print('archived')
if __name__=='__main__': main()
