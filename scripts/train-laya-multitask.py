"""Train independent type, service and safety heads on frozen Laya embeddings."""
from __future__ import annotations
import collections
import copy
import hashlib
import json
import random
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'app'))
OUT=ROOT/'.local/laya-training/retrain-2026-10-12'
TASKS={
    'post_type':('label',['service_request','recruitment','self_promotion','other']),
    'service':('service_label',['website','software','automation','other']),
    'safety':('safety_label',['A','B','review']),
}

def metrics(probabilities,targets,labels):
    import numpy as np
    if len(targets)==0:return {'count':0,'accuracy':None,'macro_f1':None}
    pred=probabilities.argmax(1)
    matrix=np.zeros((len(labels),len(labels)),dtype=int)
    for gold,chosen in zip(targets,pred):matrix[int(gold),int(chosen)]+=1
    per_class={}
    for i,label in enumerate(labels):
        tp=int(matrix[i,i]);precision=tp/max(1,int(matrix[:,i].sum()));recall=tp/max(1,int(matrix[i].sum()))
        per_class[label]={'support':int(matrix[i].sum()),'precision':precision,'recall':recall,
                         'f1':2*precision*recall/max(1e-12,precision+recall)}
    return {'count':len(targets),'accuracy':float((pred==targets).mean()),
            'macro_f1':sum(v['f1'] for v in per_class.values())/len(labels),
            'per_class':per_class,'confusion':matrix.tolist(),'label_order':labels}

def train_task(task,x,rows,vocabulary,idf,old_adapter,encoder_size):
    import numpy as np
    import torch
    from safetensors.torch import save_file
    from laya_adapter import build_post_type_head
    key,labels=TASKS[task]
    valid=[i for i,r in enumerate(rows) if r.get(key) in labels]
    target=torch.zeros(len(rows),dtype=torch.long)
    for i in valid:target[i]=labels.index(rows[i][key])
    splits={s:torch.tensor([i for i in valid if rows[i]['split']==s],dtype=torch.long)
            for s in ('train','validation','test')}
    train=splits['train'];val=splits['validation']
    if any(not len(splits[s]) for s in splits):raise ValueError(f'Empty split for {task}')
    counts=collections.Counter(target[train].tolist())
    if len(counts)!=len(labels):raise ValueError(f'Missing training class for {task}')
    hidden_size=128 if task=='post_type' else 0
    head=build_post_type_head(x.shape[1],hidden_size,len(labels))
    head.mean.copy_(x[train].mean(0));head.scale.copy_(x[train].std(0).clamp_min(.05))
    if task=='post_type':
        # Transfer the previously trained head and align lexical columns. New
        # vocabulary columns start at zero, so initial predictions equal the old
        # model rather than discarding it and learning from random weights.
        lookup={term:encoder_size+i for i,term in enumerate(vocabulary)}
        mapping=[(i,i) for i in range(encoder_size)]
        mapping.extend((encoder_size+i,lookup[term]) for i,term in enumerate(old_adapter.manifest['vocabulary']) if term in lookup)
        old=old_adapter.scorer
        with torch.no_grad():
            head.layers[0].weight.zero_()
            for old_index,new_index in mapping:
                head.mean[new_index]=old.mean[old_index];head.scale[new_index]=old.scale[old_index]
                head.layers[0].weight[:,new_index]=old.layers[0].weight[:,old_index]
            head.layers[0].bias.copy_(old.layers[0].bias)
            head.layers[3].weight.copy_(old.layers[3].weight);head.layers[3].bias.copy_(old.layers[3].bias)
    optimizer=torch.optim.AdamW(head.parameters(),lr=2e-4 if task=='post_type' else 3e-3,
                               weight_decay=.03 if task=='post_type' else .1)
    sampling=torch.tensor([1/counts[int(t)] for t in target[train]],dtype=torch.double)
    best=None;best_key=None;patience=0;history=[]
    for epoch in range(300):
        head.train();draws=train[torch.multinomial(sampling,len(train)*2,replacement=True)]
        losses=[]
        for start in range(0,len(draws),16):
            batch=draws[start:start+16]
            loss=torch.nn.functional.cross_entropy(head(x[batch]),target[batch],label_smoothing=.04)
            optimizer.zero_grad(set_to_none=True);loss.backward()
            torch.nn.utils.clip_grad_norm_(head.parameters(),1);optimizer.step();losses.append(float(loss.detach()))
        head.eval()
        with torch.no_grad():
            logits=head(x[val]);prob=torch.softmax(logits,-1).numpy()
            nll=float(torch.nn.functional.cross_entropy(logits,target[val]))
        score=metrics(prob,target[val].numpy(),labels);selection=(score['macro_f1'],-nll)
        if best_key is None or selection>best_key:
            best_key=selection;best=copy.deepcopy(head.state_dict());best_epoch=epoch+1;patience=0
        else:patience+=1
        history.append({'epoch':epoch+1,'loss':sum(losses)/len(losses),'validationMacroF1':score['macro_f1'],'validationNLL':nll})
        if epoch==0 or (epoch+1)%20==0:print(f'{task}: epoch {epoch+1}, validation F1 {score["macro_f1"]:.3f}',flush=True)
        if patience>=45:break
    head.load_state_dict(best);head.eval()
    with torch.no_grad():
        logits=head(x);temperatures=torch.linspace(.5,5,91)
        nll=[float(torch.nn.functional.cross_entropy(logits[val]/t,target[val])) for t in temperatures]
        temperature=float(temperatures[int(np.argmin(nll))]);prob=torch.softmax(logits/temperature,-1).numpy()
    threshold=.6
    if task=='post_type':
        for candidate in (.6,.65,.7,.75,.8,.85,.9,.95):
            accepted=(prob[val].argmax(1)==0)&(prob[val,0]>=candidate)
            if accepted.any() and not np.any(accepted&(target[val].numpy()!=0)):
                threshold=candidate;break
        else:threshold=.99
    if task=='safety':
        for candidate in (.6,.65,.7,.75,.8,.85,.9,.95):
            accepted=(prob[val].argmax(1)==0)&(prob[val,0]>=candidate)
            if accepted.any() and not np.any(accepted&(target[val].numpy()!=0)):
                threshold=candidate;break
        else:threshold=.99
    filename='scorer.safetensors' if task=='post_type' else f'{task}.safetensors'
    save_file({k:v.detach().contiguous() for k,v in best.items()},str(OUT/filename))
    manifest={'labels':labels,'input_size':int(x.shape[1]),'hidden_size':hidden_size,'temperature':temperature,
              'minimumConfidence':threshold,'weightsFile':filename,
              'weightsSha256':hashlib.sha256((OUT/filename).read_bytes()).hexdigest()}
    partitions={'validation':val.tolist(),
                'legacyRealTest':[i for i in splits['test'].tolist() if rows[i]['origin']=='user_paste'],
                'freshRealTest':[i for i in splits['test'].tolist() if rows[i]['origin']=='local_review'],
                'syntheticTest':[i for i in splits['test'].tolist() if rows[i]['origin']=='synthetic_assistant']}
    report={'splitCounts':{s:len(ids) for s,ids in splits.items()},'bestEpoch':best_epoch,
            'epochsRun':len(history),'minimumConfidence':threshold,'temperature':temperature,'history':history}
    for partition,ids in partitions.items():report[partition]=metrics(prob[ids],target[ids].numpy(),labels)
    predictions=[{'id':rows[i]['id'],'split':rows[i]['split'],'origin':rows[i]['origin'],
                  'task':task,'expected':rows[i][key],'predicted':labels[int(prob[i].argmax())],
                  'confidence':float(prob[i].max()),'probabilities':dict(zip(labels,map(float,prob[i])))} for i in valid]
    return manifest,report,prob,predictions

def main():
    import numpy as np
    import torch
    import laya_classifier
    from laya_adapter import encode_post,lexical_terms,lexical_vector
    torch.set_num_threads(4);torch.manual_seed(1210);random.seed(1210);np.random.seed(1210)
    rows=[json.loads(line) for line in (OUT/'dataset.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    rows=[r for r in rows if r['split']!='review_only']
    groups={s:{r['content_group'] for r in rows if r['split']==s} for s in ('train','validation','test')}
    if any(groups[a]&groups[b] for a,b in (('train','validation'),('train','test'),('validation','test'))):
        raise ValueError('Content-group leakage')
    # Always compare and warm-start against the original immutable bundled head,
    # rather than recursively blending successive locally activated models.
    import laya_adapter
    from unittest.mock import patch
    with patch.object(laya_adapter,'TRAINING_DIR',laya_adapter.BUNDLED_TRAINING_DIR),patch.object(
        laya_adapter,'ACTIVE_PATH',laya_adapter.BUNDLED_TRAINING_DIR/'active.json'):
        agent=laya_classifier._get_agent();old_adapter=laya_classifier._post_type_adapter
    config_hash=hashlib.sha256(json.dumps(agent.cfg,sort_keys=True).encode()).hexdigest()
    cache=ROOT/'.local/laya-training/encoder-text-cache';cache.mkdir(parents=True,exist_ok=True)
    features=[]
    for index,row in enumerate(rows):
        key=hashlib.sha256((config_hash+'|1024|'+row['text'][:12000]).encode()).hexdigest()
        path=cache/f'{key}.npy'
        if path.exists():feature=np.load(path)
        else:
            feature=encode_post(agent,row['text'][:12000])[0].cpu().numpy().copy();np.save(path,feature)
        features.append(feature)
        if (index+1)%10==0 or index+1==len(rows):print(f'Encoder {index+1}/{len(rows)}',flush=True)
    features=np.asarray(features,dtype=np.float32)
    train=[i for i,r in enumerate(rows) if r['split']=='train'];frequency=collections.Counter()
    for i in train:frequency.update(set(lexical_terms(rows[i]['text'])))
    vocabulary=sorted(k for k,n in frequency.most_common(3500) if n>=2)
    idf=[float(np.log((1+len(train))/(1+frequency[k]))+1) for k in vocabulary]
    lexical=np.stack([lexical_vector(r['text'],vocabulary,idf) for r in rows])
    x=torch.tensor(np.concatenate((features,lexical),axis=1))
    heads={};reports={};probabilities={};predictions=[]
    for task in TASKS:
        heads[task],reports[task],probabilities[task],prediction=train_task(task,x,rows,vocabulary,idf,old_adapter,features.shape[1])
        predictions.extend(prediction)
    labels=TASKS['post_type'][1]
    old_lexical=np.stack([lexical_vector(r['text'],old_adapter.manifest['vocabulary'],old_adapter.manifest['idf']) for r in rows])
    with torch.no_grad():
        old_logits=old_adapter.scorer(torch.tensor(np.concatenate((features,old_lexical),axis=1)))
        old_prob=torch.softmax(old_logits/old_adapter.manifest['temperature'],-1).numpy()
    old_prob=old_prob[:,[old_adapter.manifest['labels'].index(label) for label in labels]]
    # Retain the old classifier as a frozen ensemble member, reducing forgetting
    # while the new head learns the additional reviewed cases.
    probabilities['post_type']=.5*probabilities['post_type']+.5*old_prob
    # Calibrate the final ensemble, not just its individual members. Fit on
    # validation labels; never choose a temperature to force scores below 70%.
    from laya_adapter import calibrate_probabilities
    calibration_ids=[i for i,r in enumerate(rows) if r['split']=='validation']
    calibration_targets=np.array([labels.index(rows[i]['label']) for i in calibration_ids])
    raw=probabilities['post_type'].copy()
    def calibrated_nll(temp):
        q=np.array([calibrate_probabilities(p,float(temp)) for p in raw[calibration_ids]])
        return float(-np.log(q[np.arange(len(q)),calibration_targets].clip(1e-12)).mean())
    temperatures=np.linspace(.5,5,181)
    ensemble_temperature=float(temperatures[int(np.argmin([calibrated_nll(t) for t in temperatures]))])
    probabilities['post_type']=np.array([calibrate_probabilities(p,ensemble_temperature) for p in raw])
    calibration_report={'method':'temperature scaling of final ensemble',
        'fittedOn':'validation only','validationCount':len(calibration_ids),'temperature':ensemble_temperature,
        'validationNllBefore':calibrated_nll(1.),'validationNllAfter':calibrated_nll(ensemble_temperature),
        'validationMeanConfidenceBefore':float(raw[calibration_ids].max(1).mean()),
        'validationMeanConfidenceAfter':float(probabilities['post_type'][calibration_ids].max(1).mean())}
    for prediction in predictions:
        if prediction['task']=='post_type':
            index=next(i for i,r in enumerate(rows) if r['id']==prediction['id'])
            prob=probabilities['post_type'][index]
            prediction.update(predicted=labels[int(prob.argmax())],confidence=float(prob.max()),
                              probabilities=dict(zip(labels,map(float,prob))))
    type_key=TASKS['post_type'][0]
    for name,origin in (('legacyRealTest','user_paste'),('freshRealTest','local_review'),('syntheticTest','synthetic_assistant')):
        ids=[i for i,r in enumerate(rows) if r['split']=='test' and r['origin']==origin]
        reports['post_type'][name]=metrics(probabilities['post_type'][ids],np.array([labels.index(rows[i][type_key]) for i in ids]),labels)
    val_ids=[i for i,r in enumerate(rows) if r['split']=='validation']
    reports['post_type']['validation']=metrics(probabilities['post_type'][val_ids],np.array([labels.index(rows[i][type_key]) for i in val_ids]),labels)
    from safetensors.torch import save_file
    legacy_path=OUT/'legacy-scorer.safetensors'
    save_file({k:v.detach().contiguous() for k,v in old_adapter.scorer.state_dict().items()},str(legacy_path))
    legacy_config={k:old_adapter.manifest[k] for k in ('labels','input_size','hidden_size','temperature','vocabulary','idf','max_len')}
    legacy_config.update(weightsFile=legacy_path.name,weightsSha256=hashlib.sha256(legacy_path.read_bytes()).hexdigest(),blendWeight=.5)
    targets=np.array([labels.index(r['label']) for r in rows])
    baseline={}
    for name,origin in (('legacyRealTest','user_paste'),('freshRealTest','local_review')):
        ids=[i for i,r in enumerate(rows) if r['split']=='test' and r['origin']==origin]
        baseline[name]=metrics(old_prob[ids],targets[ids],labels)
    # Calibrate the complete sending decision on validation only. A low safety
    # score on an advertisement should not inflate the safety threshold for
    # genuine buyers: advertisements are independently rejected by the type gate.
    val=np.array([i for i,r in enumerate(rows) if r['split']=='validation'])
    type_prob=probabilities['post_type'];service_prob=probabilities['service'];safety_prob=probabilities['safety']
    eligible_val=np.array([i for i in val if rows[i]['label']=='service_request' and
        rows[i].get('service_label') in ('website','software','automation') and rows[i].get('safety_label')=='A'])
    best_calibration=None
    for type_threshold in np.arange(.60,1.001,.01):
        for safety_threshold in np.arange(.60,1.001,.01):
          for service_threshold in (.8,.85,.9,.95):
            chosen=(type_prob.argmax(1)==0)&(type_prob[:,0]>=type_threshold)&\
                (service_prob.argmax(1)!=3)&(service_prob[:,:3].sum(1)>=service_threshold)&\
                (safety_prob.argmax(1)==0)&(safety_prob[:,0]>=safety_threshold)
            wrong=any(chosen[i] and (rows[i]['label']!='service_request' or
                rows[i].get('safety_label') in ('review','B') or rows[i].get('service_label')=='other') for i in val)
            if wrong:continue
            key=(int(chosen[eligible_val].sum()),-float(type_threshold+safety_threshold),float(service_threshold))
            if best_calibration is None or key>best_calibration[0]:
                best_calibration=(key,float(round(type_threshold,2)),float(round(safety_threshold,2)),service_threshold)
    if best_calibration is None:raise ValueError('No valid sending threshold on validation')
    heads['post_type']['minimumConfidence']=best_calibration[1]
    heads['safety']['minimumConfidence']=best_calibration[2]
    heads['service']['minimumSupportedConfidence']=best_calibration[3]
    reports['post_type']['minimumConfidence']=best_calibration[1]
    reports['safety']['minimumConfidence']=best_calibration[2]
    test=np.array([i for i,r in enumerate(rows) if r['split']=='test'])
    fresh=np.array([i for i in test if rows[i]['origin']=='local_review'])
    accepted=(type_prob.argmax(1)==0)&(type_prob[:,0]>=heads['post_type']['minimumConfidence'])&\
             (service_prob.argmax(1)!=3)&(service_prob[:,:3].sum(1)>=heads['service']['minimumSupportedConfidence'])&\
             (safety_prob.argmax(1)==0)&(safety_prob[:,0]>=heads['safety']['minimumConfidence'])
    false_leads=sum(bool(accepted[i]) and rows[i]['label']!='service_request' for i in test)
    false_safe=sum(bool(accepted[i]) and rows[i].get('safety_label','A')!='A' for i in test)
    false_scope=sum(bool(accepted[i]) and rows[i].get('service_label')=='other' for i in test)
    eligible=[i for i in test if rows[i]['label']=='service_request' and rows[i].get('service_label') in ('website','software','automation') and rows[i].get('safety_label')=='A']
    accepted_recall=sum(bool(accepted[i]) for i in eligible)/max(1,len(eligible))
    legacy=np.array([i for i in test if rows[i]['origin']=='user_paste'])
    old_buyer_accuracy=float(((old_prob[legacy].argmax(1)==0)==(targets[legacy]==0)).mean())
    new_buyer_accuracy=float(((type_prob[legacy].argmax(1)==0)==(targets[legacy]==0)).mean())
    gates={
        'legacyBuyerNoRegression':new_buyer_accuracy>=old_buyer_accuracy,
        'freshTypeNoRegression':reports['post_type']['freshRealTest']['accuracy']>=baseline['freshRealTest']['accuracy'],
        'freshTypeAccuracy':reports['post_type']['freshRealTest']['accuracy']>=.8,
        'serviceFreshAccuracy':reports['service']['freshRealTest']['accuracy']>=.7,
        'noAcceptedNonBuyers':false_leads==0,
        'noAcceptedReviewOrUnsafe':false_safe==0,
        'noAcceptedOutOfScope':false_scope==0,
        'supportedSafeRequestRecall':accepted_recall>=.6,
    }
    corrections={}
    expected={'1616674009938577':('service_request','website','A'),'1810012270111779':('service_request','automation','review'),'1810022200110786':('other','automation','A'),
              '2227569228183167':('service_request','automation','A')}
    for identifier,wanted in expected.items():
        row=next(i for i,r in enumerate(rows) if r['id']==identifier)
        chosen=tuple(TASKS[task][1][int(probabilities[task][row].argmax())] for task in TASKS)
        corrections[identifier]={'expected':wanted,'predicted':chosen,'accepted':bool(accepted[row])}
    gates['reportedExamples']=all(tuple(v['expected'])==tuple(v['predicted']) for v in corrections.values()) and corrections['1616674009938577']['accepted'] and not corrections['1810012270111779']['accepted'] and not corrections['1810022200110786']['accepted']
    gates['reportedExamples']=gates['reportedExamples'] and corrections['2227569228183167']['accepted']
    passed=all(gates.values())
    type_head=heads['post_type']
    manifest={'format':'laya-encoder-lexical-head-v1','baseModel':laya_classifier.MODEL,'baseConfigSha256':config_hash,
              'labels':labels,'input_size':type_head['input_size'],'hidden_size':128,'temperature':type_head['temperature'],
              'minimumPostTypeConfidence':type_head['minimumConfidence'],'vocabulary':vocabulary,'idf':idf,'max_len':1024,
              'weightsSha256':type_head['weightsSha256'],'datasetSha256':hashlib.sha256((OUT/'dataset.jsonl').read_bytes()).hexdigest(),
              'trainableModule':'Three separately trained classification heads with frozen Laya encoder and train-only TF-IDF',
              'frozenModules':['Laya encoder','original Laya heads'],'runVersion':'2026-10-12-type-service-safety-v3-crawlers',
              'auxiliaryHeads':{k:v for k,v in heads.items() if k!='post_type'},'strictServiceRequestOnly':True,
              'legacyClassifier':legacy_config,'passedLocalHoldoutGate':bool(passed)}
    manifest['ensembleTemperature']=ensemble_temperature
    manifest['bundleSha256']=hashlib.sha256(json.dumps({**{task:head['weightsSha256'] for task,head in heads.items()},'legacy':legacy_config['weightsSha256'],'ensembleTemperature':ensemble_temperature},sort_keys=True).encode()).hexdigest()
    report={'passedLocalHoldoutGate':bool(passed),'gates':gates,'baselineActiveModel':baseline,
            'tasks':reports,'corrections':corrections,'acceptedNonBuyerCount':false_leads,
            'acceptedReviewOrUnsafeCount':false_safe,'supportedSafeRequestRecall':accepted_recall,
            'acceptedOutOfScopeCount':false_scope,
            'confidenceCalibration':calibration_report,
            'legacyBuyerAccuracy':{'before':old_buyer_accuracy,'after':new_buyer_accuracy},
            'validationSendingCalibration':{'type':best_calibration[1],'safety':best_calibration[2],
                'supportedService':best_calibration[3],
                'acceptedSupportedSafeBuyers':best_calibration[0][0],'supportedSafeBuyers':len(eligible_val)},
            'limitations':['Only 15 fresh real posts held out; not a production accuracy estimate.',
                'Labels assigned by the assistant from text, not independently certified by the user.',
                'The three reported examples are training corrections, not independent tests.',
                'Unsafe examples include clearly tagged synthetic data.',
                'Epoch, temperature and thresholds chosen on validation only; test is checked after selection.',
                'Test summaries were inspected across candidate development; these are exploratory holdout checks.']}
    (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'predictions.jsonl').write_text(''.join(json.dumps(p,ensure_ascii=False)+'\n' for p in predictions),encoding='utf-8')
    summary={k:v for k,v in report.items() if k!='tasks'}
    summary['taskTestMetrics']={task:{k:v for k,v in report.items() if k in ('legacyRealTest','freshRealTest','syntheticTest','minimumConfidence')} for task,report in reports.items()}
    print(json.dumps(summary,ensure_ascii=True,indent=2),flush=True)

if __name__=='__main__':main()
