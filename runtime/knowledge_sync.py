from __future__ import annotations
import argparse
from pathlib import Path
from common import load_json_or_yaml_like

ROOT=Path(__file__).resolve().parents[2]
TRIGGERS={
 'responsibility':'knowledge/domains or knowledge/flows',
 'state ownership':'knowledge/domains or decisions',
 'interface':'knowledge/domains or decisions',
 'lifecycle':'knowledge/flows or decisions',
 'legacy':'knowledge/debt',
 'glossary':'knowledge/glossary',
 'benchmark':'knowledge/domains or verification guidance',
}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('change',type=Path); args=ap.parse_args()
    texts=[]
    for n in ['proposal.md','design.md','verification.md','archive-summary.md']:
        p=args.change/n
        if p.exists(): texts.append(p.read_text(encoding='utf-8').lower())
    blob='\n'.join(texts)
    print('# Knowledge Sync Hints')
    found=False
    for term,target in TRIGGERS.items():
        if term in blob:
            found=True; print(f'- {term}: review {target}')
    if not found: print('- no deterministic trigger found; semantic review still required')
if __name__=='__main__': main()
