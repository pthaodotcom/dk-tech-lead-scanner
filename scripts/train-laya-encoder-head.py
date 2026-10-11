"""Train a four-label classifier on frozen Laya encoder representations on CPU."""
from __future__ import annotations

import collections
import copy
import hashlib
import importlib.util
import json
import random
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
spec=importlib.util.spec_from_file_location('native_training',ROOT/'scripts/train-laya-post-types.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
metrics=module.metrics


def main():
    import numpy as np
    import torch
    from safetensors.torch import save_file
    import laya_classifier
    from laya_adapter import build_post_type_head,encode_post,lexical_terms,lexical_vector

    torch.set_num_threads(4); torch.manual_seed(882);random.seed(882);np.random.seed(882)
    out=ROOT/'.local/laya-training/encoder-head-v1';out.mkdir(parents=True,exist_ok=True)
    rows=[json.loads(line) for line in (ROOT/'data/laya/post_type_dataset.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    rows=[r for r in rows if r['split']!='review_only']
    questions=json.loads((ROOT/'data/laya/post_type_question.json').read_text(encoding='utf-8'))
    labels=list(questions['post_type']['criteria'])
    fingerprint=hashlib.sha256(json.dumps({'rows':rows,'base':laya_classifier.MODEL,'max_len':1024,'pooling':'cls+masked-mean'},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    cache=ROOT/'.local/laya-training'/f'encoder-features-{fingerprint[:16]}.npz'
    agent=laya_classifier._get_agent()
    if cache.exists():
        features=np.load(cache)['features']
    else:
        features=[]
        for i,row in enumerate(rows):
            features.append(encode_post(agent,row['text'][:12000])[0].cpu().numpy().copy())
            if (i+1)%10==0 or i+1==len(rows):
                print(f'Encoder representations {i+1}/{len(rows)}',flush=True)
        features=np.asarray(features,dtype=np.float32)
        np.savez_compressed(cache,features=features)
    x=torch.tensor(features);y=torch.tensor([labels.index(r['label']) for r in rows])
    partitions={name:torch.tensor([i for i,r in enumerate(rows) if r['split']==name]) for name in ('train','validation','test')}
    groups={name:{rows[i]['content_group'] for i in ids.tolist()} for name,ids in partitions.items()}
    if any(groups[a]&groups[b] for a,b in (('train','validation'),('train','test'),('validation','test'))):
        raise ValueError('Content-group leakage')
    train=partitions['train'];val=partitions['validation'];test=partitions['test']
    # Auxiliary word/bigram features are learned from training text only. They let a
    # small corpus retain rare intent cues (CV, salary, "mình cần") alongside encoder semantics.
    document_frequency=collections.Counter()
    for i in train.tolist():
        document_frequency.update(set(lexical_terms(rows[i]['text'][:12000])))
    vocabulary=sorted(term for term,count in document_frequency.most_common(3500) if count>=2)
    idf=[float(np.log((1+len(train))/(1+document_frequency[term]))+1) for term in vocabulary]
    lexical=np.stack([lexical_vector(row['text'][:12000],vocabulary,idf) for row in rows])
    x=torch.cat((x,torch.tensor(lexical)),dim=-1)
    head=build_post_type_head(x.shape[-1],128,len(labels))
    head.mean.copy_(x[train].mean(dim=0));head.scale.copy_(x[train].std(dim=0).clamp_min(.05))
    optimizer=torch.optim.AdamW(head.parameters(),lr=1e-3,weight_decay=.03)
    counts=collections.Counter(y[train].tolist())
    weights=torch.tensor([1/counts[int(label)] for label in y[train]],dtype=torch.double)
    best=None;best_key=None;patience=0;history=[]
    for epoch in range(400):
        head.train();indices=train[torch.multinomial(weights,len(train)*2,replacement=True)]
        loss_sum=0.;batches=0
        for start in range(0,len(indices),16):
            selected=indices[start:start+16]
            loss=torch.nn.functional.cross_entropy(head(x[selected]),y[selected],label_smoothing=.04)
            optimizer.zero_grad(set_to_none=True);loss.backward();torch.nn.utils.clip_grad_norm_(head.parameters(),1.);optimizer.step()
            loss_sum+=float(loss.detach());batches+=1
        head.eval()
        with torch.no_grad():
            logits=head(x[val]);prob=torch.softmax(logits,dim=-1).numpy()
            nll=float(torch.nn.functional.cross_entropy(logits,y[val]))
        score=metrics(prob,y[val].numpy(),labels)
        key=(score['macro_f1'],-nll)
        if best_key is None or key>best_key:
            best_key=key;best=copy.deepcopy(head.state_dict());best_epoch=epoch+1;patience=0
        else:patience+=1
        history.append({'epoch':epoch+1,'trainLoss':loss_sum/batches,'validationMacroF1':score['macro_f1'],'validationNLL':nll})
        if epoch==0 or (epoch+1)%10==0:print(f'epoch {epoch+1}: loss {loss_sum/batches:.4f}, validation macro-F1 {score["macro_f1"]:.4f}, NLL {nll:.4f}',flush=True)
        if patience>=50:break
    head.load_state_dict(best);head.eval()
    with torch.no_grad():
        logits=head(x)
        temperatures=torch.linspace(.5,5,91)
        losses=[float(torch.nn.functional.cross_entropy(logits[val]/t,y[val])) for t in temperatures]
        temperature=float(temperatures[int(np.argmin(losses))])
        probabilities=torch.softmax(logits/temperature,dim=-1).numpy()
    test_real=torch.tensor([i for i in test.tolist() if rows[i]['origin']=='user_paste'])
    test_synthetic=torch.tensor([i for i in test.tolist() if rows[i]['origin']=='synthetic_assistant'])
    baseline_probabilities=[]
    for i in test_real.tolist():
        answer=agent.predict(rows[i]['text'][:12000],questions,max_len=1024,head_max_len=256)['answers']['post_type']
        baseline_probabilities.append([answer['probabilities'][label] for label in labels])
    baseline_report=metrics(np.asarray(baseline_probabilities),y[test_real].numpy(),labels)
    measured=metrics(probabilities[test_real],y[test_real].numpy(),labels)
    synthetic_measured=metrics(probabilities[test_synthetic],y[test_synthetic].numpy(),labels)
    # Choose the send threshold from validation only, then measure it unchanged on test.
    threshold=.6
    for value in (.6,.65,.7,.75,.8,.85,.9,.95):
        pred=probabilities[val].argmax(axis=1)
        accepted=(pred==labels.index('service_request'))&(probabilities[val].max(axis=1)>=value)
        if not np.any(accepted&(y[val].numpy()!=labels.index('service_request'))):
            threshold=value;break
    predicted=probabilities[test_real].argmax(axis=1)
    accepted=(predicted==labels.index('service_request'))&(probabilities[test_real].max(axis=1)>=threshold)
    false_leads=int(np.sum(accepted&(y[test_real].numpy()!=labels.index('service_request'))))
    request_recall=float(np.sum(accepted&(y[test_real].numpy()==labels.index('service_request')))/max(1,np.sum(y[test_real].numpy()==labels.index('service_request'))))
    acceptance=measured['macro_f1']>baseline_report['macro_f1'] and measured['accuracy']>=baseline_report['accuracy'] and false_leads==0 and request_recall>=.6 and synthetic_measured['accuracy']>=.8
    weights_path=out/'scorer.safetensors';save_file({key:v.detach().contiguous() for key,v in best.items()},str(weights_path))
    manifest={'format':'laya-encoder-lexical-head-v1','baseModel':laya_classifier.MODEL,'baseConfigSha256':hashlib.sha256(json.dumps(agent.cfg,sort_keys=True).encode()).hexdigest(),
              'questions':questions,'labels':labels,'input_size':int(x.shape[-1]),'hidden_size':128,'temperature':temperature,'minimumPostTypeConfidence':threshold,
              'vocabulary':vocabulary,'idf':idf,
              'max_len':1024,'weightsSha256':hashlib.sha256(weights_path.read_bytes()).hexdigest(),'datasetSha256':fingerprint,
              'trainableModule':'Four-way classifier using frozen Laya encoder and training-only TF-IDF features','trainableParameters':sum(p.numel() for p in head.parameters()),
              'frozenModules':['Laya encoder','original Laya heads'],'runVersion':'2026-10-11-trained-encoder-lexical-head-v1','passedLocalHoldoutGate':acceptance}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    report={'dataset':fingerprint,'splitCounts':{key:len(ids) for key,ids in partitions.items()},'bestEpoch':best_epoch,'epochsRun':len(history),'temperature':temperature,
            'baselineSameVietnameseQuestion':baseline_report,'trainedHeldoutUserPosts':measured,'syntheticRecruitmentTest':synthetic_measured,'minimumPostTypeConfidence':threshold,
            'highConfidenceFalseLeads':false_leads,'qualifiedServiceRequestRecall':request_recall,'passedLocalHoldoutGate':acceptance,'history':history,
            'limitations':['Assistant labels are not independently user-certified.','19 real evaluation posts; the only real recruitment post is used for training, so recruitment evaluation is synthetic only.','Training and validation include explicitly tagged synthetic examples.','Held-out results are exploratory: several candidate iterations inspected this partition.','Only the added classification head and training-only lexical vocabulary are learned; the Laya encoder stays frozen.']}
    (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    predictions=[]
    for i,row in enumerate(rows):
        predictions.append({'id':row['id'],'split':row['split'],'origin':row['origin'],'expected':row['label'],'trained':labels[int(probabilities[i].argmax())],'confidence':float(probabilities[i].max()),'text':row['text']})
    (out/'predictions.jsonl').write_text(''.join(json.dumps(p,ensure_ascii=False)+'\n' for p in predictions),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='history'},indent=2),flush=True)


if __name__=='__main__':main()
