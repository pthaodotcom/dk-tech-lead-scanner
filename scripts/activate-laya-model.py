"""Publish a verified local candidate as an immutable local release, then switch the pointer."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('candidate',type=Path)
    args=parser.parse_args()
    candidate=args.candidate.resolve()
    training=(ROOT/'.local/laya-training').resolve()
    if not candidate.is_relative_to(training):
        raise ValueError('Candidate must be a local training artifact')
    manifest=json.loads((candidate/'manifest.json').read_text(encoding='utf-8'))
    report=json.loads((candidate/'report.json').read_text(encoding='utf-8'))
    if not manifest.get('passedLocalHoldoutGate') or not report.get('passedLocalHoldoutGate'):
        raise ValueError('Candidate did not pass local evaluation')
    digest=hashlib.sha256((candidate/'scorer.safetensors').read_bytes()).hexdigest()
    if digest!=manifest['weightsSha256']:
        raise ValueError('Candidate weights checksum differs from manifest')
    release=training/'releases'/digest[:16]
    release.mkdir(parents=True,exist_ok=True)
    for filename in ('scorer.safetensors','manifest.json','report.json','predictions.jsonl'):
        shutil.copy2(candidate/filename,release/filename)
    active={'directory':str(release.relative_to(training)).replace('\\','/'),
            'weightsSha256':digest,'runVersion':manifest['runVersion']}
    temporary=training/'active.json.tmp'
    temporary.write_text(json.dumps(active,indent=2),encoding='utf-8')
    temporary.replace(training/'active.json')
    print(json.dumps(active,indent=2))


if __name__=='__main__':main()
