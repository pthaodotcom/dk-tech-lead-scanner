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
    parser.add_argument('--allow-conservative-recall',action='store_true',
                        help='Explicitly deploy when only the recall target failed; all other checks must pass.')
    args=parser.parse_args()
    candidate=args.candidate.resolve()
    training=(ROOT/'.local/laya-training').resolve()
    if not candidate.is_relative_to(training):
        raise ValueError('Candidate must be a local training artifact')
    manifest=json.loads((candidate/'manifest.json').read_text(encoding='utf-8'))
    report=json.loads((candidate/'report.json').read_text(encoding='utf-8'))
    if not manifest.get('passedLocalHoldoutGate') or not report.get('passedLocalHoldoutGate'):
        failures={key for key,value in report.get('gates',{}).items() if not value}
        if not args.allow_conservative_recall or failures!={'supportedSafeRequestRecall'}:
            raise ValueError('Candidate did not pass local evaluation')
        manifest['approvedConservativeDeployment']=True
        manifest['deploymentLimitation']='Supported safe request recall 4/7; explicit user requested deployment.'
    digest=hashlib.sha256((candidate/'scorer.safetensors').read_bytes()).hexdigest()
    if digest!=manifest['weightsSha256']:
        raise ValueError('Candidate weights checksum differs from manifest')
    auxiliary=manifest.get('auxiliaryHeads',{})
    if manifest.get('legacyClassifier'):
        auxiliary={**auxiliary,'legacy':manifest['legacyClassifier']}
    for config in auxiliary.values():
        path=(candidate/config['weightsFile']).resolve()
        if not path.is_relative_to(candidate) or hashlib.sha256(path.read_bytes()).hexdigest()!=config['weightsSha256']:
            raise ValueError('Auxiliary weights checksum or path is invalid')
    release=training/'releases'/manifest.get('bundleSha256',digest)[:16]
    release.mkdir(parents=True,exist_ok=True)
    for filename in ('scorer.safetensors','manifest.json','report.json','predictions.jsonl'):
        shutil.copy2(candidate/filename,release/filename)
    for config in auxiliary.values():
        shutil.copy2(candidate/config['weightsFile'],release/config['weightsFile'])
    (release/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    active={'directory':str(release.relative_to(training)).replace('\\','/'),
            'weightsSha256':digest,'runVersion':manifest['runVersion']}
    temporary=training/'active.json.tmp'
    temporary.write_text(json.dumps(active,indent=2),encoding='utf-8')
    temporary.replace(training/'active.json')
    print(json.dumps(active,indent=2))


if __name__=='__main__':main()
