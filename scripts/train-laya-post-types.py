"""Fine-tune Laya's native scorer with frozen encoder/attention heads on local labelled posts.

Frozen marker representations are cached once for CPU training. The saved safetensors
contains trained Laya scorer parameters, not a keyword table or a list of memorized IDs.
"""
from __future__ import annotations

import argparse
import collections
import copy
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))


def metrics(probabilities, targets, labels):
    import numpy as np
    predicted = probabilities.argmax(axis=1)
    confusion = np.zeros((len(labels),len(labels)),dtype=int)
    for gold, pred in zip(targets,predicted):
        confusion[gold,pred] += 1
    per_class = {}
    for i,label in enumerate(labels):
        tp=int(confusion[i,i]); support=int(confusion[i].sum())
        precision=tp/max(1,int(confusion[:,i].sum())); recall=tp/max(1,support)
        per_class[label] = {"support":support,"precision":round(precision,4),"recall":round(recall,4),"f1":round(2*precision*recall/max(1e-12,precision+recall),4)}
    return {"count":len(targets),"accuracy":round(float((predicted==targets).mean()),4),
            "macro_f1":round(sum(p['f1'] for p in per_class.values())/len(labels),4),
            "false_leads":int(((predicted==labels.index('service_request')) & (targets!=labels.index('service_request'))).sum()),
            "per_class":per_class,"confusion":confusion.tolist(),"label_order":labels}


def main():
    import numpy as np
    import torch
    from safetensors.torch import save_file
    import laya_classifier

    parser=argparse.ArgumentParser()
    parser.add_argument('--epochs',type=int,default=240)
    parser.add_argument('--out',type=Path,default=ROOT/'.local/laya-training/post-types-v1')
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    torch.set_num_threads(4)
    torch.manual_seed(411); random.seed(411); np.random.seed(411)
    rows=[json.loads(line) for line in (ROOT/'data/laya/post_type_dataset.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    rows=[row for row in rows if row['split']!='review_only']
    questions=json.loads((ROOT/'data/laya/post_type_question.json').read_text(encoding='utf-8'))
    labels=list(questions['post_type']['criteria'])
    fingerprint=hashlib.sha256(json.dumps({'rows':rows,'questions':questions,'base':laya_classifier.MODEL,'max_len':1024,'head_max_len':256},ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest()
    cache=ROOT/'.local/laya-training'/f'features-{fingerprint[:16]}.npz'
    agent=laya_classifier._get_agent()
    if cache.exists():
        saved=np.load(cache)
        features=saved['features']; baseline=saved['baseline']
        print(f'Loaded cached representations for {len(rows)} samples',flush=True)
    else:
        captured=[]
        def capture(module,arguments):
            captured.append(arguments[0].detach().float().cpu().numpy().copy())
        hook=agent.model.scorer.register_forward_pre_hook(capture)
        features=[]; baseline=[]
        try:
            for i,row in enumerate(rows):
                result=agent.predict(row['text'][:12000],questions,max_len=1024,head_max_len=256)
                feature=captured.pop()[0]
                if feature.shape[0] != len(labels):
                    raise ValueError('Question options truncated during tokenization')
                features.append(feature)
                probability=result['answers']['post_type']['probabilities']
                baseline.append([probability[label] for label in labels])
                if (i+1)%10==0 or i+1==len(rows):
                    print(f'Frozen Laya features {i+1}/{len(rows)}',flush=True)
        finally:
            hook.remove()
        features=np.asarray(features,dtype=np.float32); baseline=np.asarray(baseline,dtype=np.float32)
        np.savez_compressed(cache,features=features,baseline=baseline)
    x=torch.tensor(features,dtype=torch.float32)
    y=torch.tensor([labels.index(r['label']) for r in rows],dtype=torch.long)
    partitions={name:np.array([i for i,r in enumerate(rows) if r['split']==name],dtype=int) for name in ('train','validation','test')}
    split_groups={name:{rows[i]['content_group'] for i in ids} for name,ids in partitions.items()}
    if any(split_groups[a]&split_groups[b] for a,b in (('train','validation'),('train','test'),('validation','test'))):
        raise ValueError('Content-group leakage between train, validation and test')
    train=partitions['train']; validation=partitions['validation']; test=partitions['test']
    train_idx=torch.tensor(train); val_idx=torch.tensor(validation)
    counts=collections.Counter(y[train_idx].tolist())
    sampling=torch.tensor([1/counts[int(target)] for target in y[train_idx]],dtype=torch.double)
    scorer=copy.deepcopy(agent.model.scorer).float().requires_grad_(True)
    optimizer=torch.optim.AdamW(scorer.parameters(),lr=3e-4,weight_decay=.01)
    best=None; best_key=None; bad_epochs=0; history=[]
    for epoch in range(args.epochs):
        scorer.train()
        draws=torch.multinomial(sampling,len(train)*2,replacement=True)
        epoch_loss=0.; batches=0
        for offset in range(0,len(draws),16):
            indices=train_idx[draws[offset:offset+16]]
            logits=scorer(x[indices]).squeeze(-1)
            loss=torch.nn.functional.cross_entropy(logits,y[indices],label_smoothing=.02)
            optimizer.zero_grad(set_to_none=True); loss.backward()
            torch.nn.utils.clip_grad_norm_(scorer.parameters(),1.)
            optimizer.step(); epoch_loss+=float(loss.detach()); batches+=1
        scorer.eval()
        with torch.no_grad():
            val_logits=scorer(x[val_idx]).squeeze(-1)
            val_prob=torch.softmax(val_logits,dim=-1).numpy()
            val_loss=float(torch.nn.functional.cross_entropy(val_logits,y[val_idx]))
        val_metrics=metrics(val_prob,y[val_idx].numpy(),labels)
        key=(val_metrics['macro_f1'], -val_loss)
        if best_key is None or key>best_key:
            best_key=key; best=copy.deepcopy(scorer.state_dict()); best_epoch=epoch+1; bad_epochs=0
        else:
            bad_epochs+=1
        history.append({'epoch':epoch+1,'train_loss':epoch_loss/batches,'validation_loss':val_loss,'validation_macro_f1':val_metrics['macro_f1']})
        if epoch==0 or (epoch+1)%10==0:
            print(f"epoch {epoch+1}: loss {epoch_loss/batches:.4f}, validation macro-F1 {val_metrics['macro_f1']:.4f}, val NLL {val_loss:.4f}",flush=True)
        if bad_epochs>=35:
            break
    scorer.load_state_dict(best); scorer.eval()
    with torch.no_grad():
        logits=scorer(x).squeeze(-1)
        candidate_temperatures=torch.linspace(.5,5.,91)
        calibration_loss=[float(torch.nn.functional.cross_entropy(logits[val_idx]/temp,y[val_idx])) for temp in candidate_temperatures]
        temperature=float(candidate_temperatures[int(np.argmin(calibration_loss))])
        trained=torch.softmax(logits/temperature,dim=-1).numpy()
    baseline_test=metrics(baseline[test],y[test].numpy(),labels)
    trained_test=metrics(trained[test],y[test].numpy(),labels)
    acceptance=trained_test['macro_f1']>baseline_test['macro_f1'] and trained_test['accuracy']>=baseline_test['accuracy'] and trained_test['false_leads']==0 and trained_test['per_class']['service_request']['recall']>=.6
    weights=args.out/'scorer.safetensors'
    save_file({key:value.detach().cpu().contiguous() for key,value in best.items()},str(weights))
    manifest={'format':'laya-native-scorer-v1','baseModel':laya_classifier.MODEL,'baseConfigSha256':hashlib.sha256(json.dumps(agent.cfg,sort_keys=True).encode()).hexdigest(),
              'questions':questions,'temperature':temperature,'max_len':1024,'head_max_len':256,'weightsSha256':hashlib.sha256(weights.read_bytes()).hexdigest(),
              'datasetSha256':fingerprint,'trainableModule':'DecisionModel.scorer','trainableParameters':sum(p.numel() for p in scorer.parameters()),
              'frozenModules':['encoder','head','type_emb','act_head'],'runVersion':'2026-10-11-trained-post-types-v1','passedLocalHoldoutGate':acceptance}
    (args.out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    report={'dataset':fingerprint,'splitCounts':{key:len(value) for key,value in partitions.items()},'bestEpoch':best_epoch,'epochsRun':len(history),
            'temperature':temperature,'baselineHeldoutUserPosts':baseline_test,'trainedHeldoutUserPosts':trained_test,'passedLocalHoldoutGate':acceptance,
            'history':history,'limitations':['Labels were assigned by the assistant, not independently certified by the user.','Only one real recruitment post is present; synthetic recruitment examples supplement training and validation.','Held-out evaluation is small and local; it does not establish production accuracy.','Validation data selects the epoch and temperature; test data does neither.']}
    (args.out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    predictions=[]
    for i,row in enumerate(rows):
        predictions.append({'id':row['id'],'split':row['split'],'origin':row['origin'],'expected':row['label'],'baseline':labels[int(baseline[i].argmax())],
                            'trained':labels[int(trained[i].argmax())],'confidence':float(trained[i].max()),'text':row['text']})
    (args.out/'predictions.jsonl').write_text(''.join(json.dumps(p,ensure_ascii=False)+'\n' for p in predictions),encoding='utf-8')
    print(json.dumps({key:value for key,value in report.items() if key!='history'},ensure_ascii=True,indent=2),flush=True)


if __name__=='__main__':
    main()
