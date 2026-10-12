"""Load a trained post-type head on the frozen local Laya encoder."""
from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_TRAINING_DIR = ROOT / ".local/laya-training"
BUNDLED_TRAINING_DIR = ROOT / "models/laya-post-type"
def select_training_dir(local=LOCAL_TRAINING_DIR, bundled=BUNDLED_TRAINING_DIR):
    """A Git update must not be hidden by an older locally activated release."""
    if not (local/'active.json').is_file():
        return bundled
    def release_rank(root):
        active=json.loads((root/'active.json').read_text(encoding='utf-8'))
        directory=(root/active['directory']).resolve()
        if not directory.is_relative_to(root.resolve()):
            raise ValueError('Model directory must stay inside its model root')
        manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
        version=manifest.get('runVersion','')
        match=re.search(r'-v(\d+)(?:-|$)',version)
        return (version[:10],int(match.group(1)) if match else 0)
    try:
        return bundled if release_rank(bundled)>release_rank(local) else local
    except (OSError,ValueError,KeyError,TypeError):
        return local


TRAINING_DIR = select_training_dir()
ACTIVE_PATH = TRAINING_DIR / "active.json"


def calibrate_probabilities(probabilities, temperature=1.0):
    """Temperature scaling preserves the selected label, adjusts its confidence."""
    if not math.isfinite(temperature) or temperature <= 0:
        raise ValueError('Calibration temperature must be positive and finite')
    logits=[math.log(max(float(p),1e-12))/temperature for p in probabilities]
    maximum=max(logits)
    values=[math.exp(value-maximum) for value in logits]
    total=sum(values)
    return [value/total for value in values]


def build_post_type_head(input_size: int, hidden_size: int, classes: int):
    import torch
    from torch import nn

    class EncoderPostTypeHead(nn.Module):
        def __init__(self):
            super().__init__()
            self.register_buffer("mean", torch.zeros(input_size))
            self.register_buffer("scale", torch.ones(input_size))
            self.layers = (nn.Sequential(nn.Linear(input_size,hidden_size),nn.GELU(),
                                        nn.Dropout(.15),nn.Linear(hidden_size,classes))
                           if hidden_size else nn.Sequential(nn.Linear(input_size,classes)))

        def forward(self, representations):
            return self.layers((representations-self.mean)/self.scale)

    return EncoderPostTypeHead()


def encode_post(agent, text: str, max_len: int = 1024):
    import torch

    tokens = agent.tok(text, return_tensors="pt", truncation=True, max_length=max_len)
    tokens = {key: value.to(agent.device) for key,value in tokens.items()
              if key in {"input_ids","attention_mask"}}
    with torch.inference_mode():
        state = agent.model.encoder(**tokens).last_hidden_state.float()
        mask = tokens["attention_mask"].unsqueeze(-1)
        mean = (state*mask).sum(dim=1)/mask.sum(dim=1).clamp_min(1)
        return torch.cat((state[:,0],mean),dim=-1)


def lexical_terms(text: str):
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"https?://\S+", " url ", text)
    text = re.sub(r"\d+", " number ", text)
    words = re.findall(r"[^\W_]+", text, flags=re.UNICODE)
    return words + [words[i]+" "+words[i+1] for i in range(len(words)-1)]


def lexical_vector(text: str, vocabulary: list[str], idf: list[float]):
    import numpy as np
    counts = Counter(lexical_terms(text))
    vector = np.array([(1+np.log(counts[term]))*weight if counts[term] else 0
                       for term,weight in zip(vocabulary,idf)],dtype=np.float32)
    norm = np.linalg.norm(vector)
    return vector/norm if norm else vector


class PostTypeAdapter:
    def __init__(self, agent):
        from safetensors.torch import load_file

        active = json.loads(ACTIVE_PATH.read_text(encoding="utf-8"))
        directory = (TRAINING_DIR / active["directory"]).resolve()
        if not directory.is_relative_to(TRAINING_DIR.resolve()):
            raise ValueError("Model directory must stay inside the selected model directory")
        self.manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        if self.manifest["format"] != "laya-encoder-lexical-head-v1" or not (
            self.manifest.get("passedLocalHoldoutGate") or self.manifest.get('approvedConservativeDeployment')):
            raise ValueError("The trained post-type scorer has not passed its local holdout gate")
        config_hash = hashlib.sha256(json.dumps(agent.cfg, sort_keys=True).encode()).hexdigest()
        if config_hash != self.manifest["baseConfigSha256"]:
            raise ValueError("The trained scorer does not match the loaded Laya base config")
        weights = directory / "scorer.safetensors"
        if hashlib.sha256(weights.read_bytes()).hexdigest() != self.manifest["weightsSha256"]:
            raise ValueError("The trained scorer's checksum is invalid")
        self.scorer = build_post_type_head(self.manifest["input_size"],self.manifest["hidden_size"],len(self.manifest["labels"]))
        self.scorer.load_state_dict(load_file(str(weights)), strict=True)
        parameter = next(agent.model.scorer.parameters())
        self.scorer.to(device=parameter.device, dtype=parameter.dtype).eval().requires_grad_(False)
        self.directory = directory
        self.auxiliary_heads = {}
        self.legacy_classifier = None
        for name, config in self.manifest.get('auxiliaryHeads', {}).items():
            if name not in {'service', 'safety'}:
                raise ValueError('Unknown auxiliary classifier')
            path = (directory / config['weightsFile']).resolve()
            if not path.is_relative_to(directory) or hashlib.sha256(path.read_bytes()).hexdigest() != config['weightsSha256']:
                raise ValueError('Invalid auxiliary classifier checksum or path')
            if config['input_size'] != self.manifest['input_size']:
                raise ValueError('Auxiliary classifier feature dimensions differ')
            head = build_post_type_head(config['input_size'],config['hidden_size'],len(config['labels']))
            head.load_state_dict(load_file(str(path)),strict=True)
            head.to(device=parameter.device,dtype=parameter.dtype).eval().requires_grad_(False)
            self.auxiliary_heads[name] = (head,config)
        config=self.manifest.get('legacyClassifier')
        if config:
            path=(directory/config['weightsFile']).resolve()
            if not path.is_relative_to(directory) or hashlib.sha256(path.read_bytes()).hexdigest()!=config['weightsSha256']:
                raise ValueError('Invalid legacy classifier checksum or path')
            if set(config['labels'])!=set(self.manifest['labels']) or not 0<=config['blendWeight']<=1:
                raise ValueError('Invalid ensemble configuration')
            head=build_post_type_head(config['input_size'],config['hidden_size'],len(config['labels']))
            head.load_state_dict(load_file(str(path)),strict=True)
            head.to(device=parameter.device,dtype=parameter.dtype).eval().requires_grad_(False)
            self.legacy_classifier=(head,config)

    def predict(self, agent, text: str) -> dict:
        return self.predict_all(agent,text)['post_type']

    def predict_all(self, agent, text: str) -> dict:
        import torch
        with torch.inference_mode():
            representation = encode_post(agent,text,self.manifest["max_len"])
            encoder_representation=representation
            lexical = torch.tensor(lexical_vector(text,self.manifest["vocabulary"],self.manifest["idf"]),device=representation.device)
            representation = torch.cat((representation,lexical.unsqueeze(0)),dim=-1)
            answers={}
            heads={'post_type':(self.scorer,self.manifest),**self.auxiliary_heads}
            for name,(head,config) in heads.items():
                probabilities=torch.softmax(head(representation)/config['temperature'],dim=-1)[0].cpu().tolist()
                labels=config['labels'];choice=max(range(len(labels)),key=probabilities.__getitem__)
                if name=='post_type' and self.legacy_classifier:
                    previous,previous_config=self.legacy_classifier
                    old_lexical=torch.tensor(lexical_vector(text,previous_config['vocabulary'],previous_config['idf']),device=representation.device)
                    old_representation=torch.cat((encoder_representation,old_lexical.unsqueeze(0)),dim=-1)
                    old_probs=torch.softmax(previous(old_representation)/previous_config['temperature'],dim=-1)[0].cpu().tolist()
                    weight=previous_config['blendWeight']
                    probabilities=[(1-weight)*p+weight*old_probs[previous_config['labels'].index(label)] for label,p in zip(labels,probabilities)]
                    probabilities=calibrate_probabilities(probabilities,self.manifest.get('ensembleTemperature',1.0))
                    choice=max(range(len(labels)),key=probabilities.__getitem__)
                answers[name]={'type':'choice','choice':labels[choice],
                    'probabilities':dict(zip(labels,probabilities)), 'answer_confidence':probabilities[choice],
                    'minimumConfidence':config.get('minimumConfidence',config.get('minimumPostTypeConfidence',.6))}
                if name=='service' and 'minimumSupportedConfidence' in config:
                    answers[name]['supportedConfidence']=sum(p for label,p in zip(labels,probabilities) if label in {'website','software','automation'})
                    answers[name]['minimumSupportedConfidence']=config['minimumSupportedConfidence']
        return answers


def load_adapter(agent):
    return PostTypeAdapter(agent) if ACTIVE_PATH.is_file() else None


def configured_model_version() -> str:
    if not ACTIVE_PATH.is_file():
        return "zero-shot"
    try:
        active = json.loads(ACTIVE_PATH.read_text(encoding="utf-8"))
        directory = (TRAINING_DIR / active["directory"]).resolve()
        if not directory.is_relative_to(TRAINING_DIR.resolve()):
            return "invalid-trained-adapter"
        manifest = json.loads((directory/"manifest.json").read_text(encoding="utf-8"))
        return manifest.get('bundleSha256',manifest["weightsSha256"])[:16]
    except (OSError,ValueError,KeyError,TypeError):
        return "invalid-trained-adapter"
