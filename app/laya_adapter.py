"""Load a trained post-type head on the frozen local Laya encoder."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_TRAINING_DIR = ROOT / ".local/laya-training"
BUNDLED_TRAINING_DIR = ROOT / "models/laya-post-type"
# Keep a locally activated model when present; a fresh checkout uses the bundled release.
TRAINING_DIR = (LOCAL_TRAINING_DIR if (LOCAL_TRAINING_DIR / "active.json").is_file()
                else BUNDLED_TRAINING_DIR)
ACTIVE_PATH = TRAINING_DIR / "active.json"


def build_post_type_head(input_size: int, hidden_size: int, classes: int):
    import torch
    from torch import nn

    class EncoderPostTypeHead(nn.Module):
        def __init__(self):
            super().__init__()
            self.register_buffer("mean", torch.zeros(input_size))
            self.register_buffer("scale", torch.ones(input_size))
            self.layers = nn.Sequential(nn.Linear(input_size,hidden_size),nn.GELU(),
                                        nn.Dropout(.15),nn.Linear(hidden_size,classes))

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
        if self.manifest["format"] != "laya-encoder-lexical-head-v1" or not self.manifest.get("passedLocalHoldoutGate"):
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

    def predict(self, agent, text: str) -> dict:
        import torch
        with torch.inference_mode():
            representation = encode_post(agent,text,self.manifest["max_len"])
            lexical = torch.tensor(lexical_vector(text,self.manifest["vocabulary"],self.manifest["idf"]),device=representation.device)
            representation = torch.cat((representation,lexical.unsqueeze(0)),dim=-1)
            logits = self.scorer(representation)
            probabilities = torch.softmax(logits/self.manifest["temperature"],dim=-1)[0].cpu().tolist()
        labels = self.manifest["labels"]
        choice_index = max(range(len(labels)),key=probabilities.__getitem__)
        return {"type":"choice","choice":labels[choice_index],
                "probabilities":dict(zip(labels,probabilities)),
                "answer_confidence":probabilities[choice_index]}


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
        return manifest["weightsSha256"][:16]
    except (OSError,ValueError,KeyError,TypeError):
        return "invalid-trained-adapter"
