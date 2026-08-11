#!/usr/bin/env python3
"""AUGURY — fine_tune_encoder.py (WS1b: contrastive fine-tune of the retrieval encoder)

Trains the retrieval encoder to separate AU weed species better, using
pytorch-metric-learning (MultiSimilarity loss + miner) on the AU image set.
Run after bake_off.py shows off-the-shelf top-1 below the gate.

Base: DINOv2-base (the AU bake-off winner) or SigLIP2-400M. Embeddings are
L2-normalised and match bake_off.py's serving contract (cosine kNN).

Usage
-----
  # install dep once (local + DSW):
  uv pip install --python .venv-mcpmv46/bin/python pytorch-metric-learning

  # A10 cloud run (the real job):
  .venv-mcpmv46/bin/python scripts/vision/fine_tune_encoder.py \
      --model dinov2-base --epochs 5 --batch-size 96 --lr 3e-4 \
      --out data/vision/ft/dinov2-au

  # local smoke (1 epoch, 2 species, few images):
  .venv-mcpmv46/bin/python scripts/vision/fine_tune_encoder.py \
      --model dinov2-base --epochs 1 --max-species 2 --limit 8 --batch-size 8 \
      --out /tmp/opencode/ft-smoke

After training, re-eval with bake_off.py:
  .venv-mcpmv46/bin/python scripts/vision/bake_off.py --au-only \
      --model-path data/vision/ft/dinov2-au --limit 30
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch.utils.data import DataLoader, Dataset
from transformers import AutoModel, AutoProcessor

from pytorch_metric_learning import miners, losses, samplers


MODELS = {
    "dinov2-base": ("facebook/dinov2-base", 768),
    "dinov2-large": ("facebook/dinov2-large", 1024),
    "siglip2-400m": ("google/siglip2-so400m-patch14-384", 1152),
}


class SpeciesImages(Dataset):
    """Images grouped by species key, with a label per species."""

    def __init__(self, images_dir, species_list, max_species=0, limit=0, seed=42):
        rng = random.Random(seed)
        au_keys = [k for k, s in species_list.items() if s.get("is_au")]
        if max_species:
            rng.shuffle(au_keys)
            au_keys = au_keys[:max_species]
        self.keys = []
        self.paths = []
        self.labels = []
        self.label_map = {}
        for key in sorted(au_keys):
            d = Path(images_dir) / key
            if not d.is_dir():
                continue
            jpgs = sorted(d.glob("*.jpg"))
            if limit:
                jpgs = jpgs[:limit]
            if not jpgs:
                continue
            lab = len(self.label_map)
            self.label_map[key] = lab
            self.keys.extend([key] * len(jpgs))
            self.paths.extend(jpgs)
            self.labels.extend([lab] * len(jpgs))

    def __len__(self):
        return len(self.paths)

    def __getitem__(self, i):
        return Image.open(self.paths[i]).convert("RGB"), self.labels[i]


def pil_collate(batch):
    imgs = [b[0] for b in batch]
    labels = torch.tensor([b[1] for b in batch])
    return imgs, labels


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="dinov2-base", choices=list(MODELS))
    ap.add_argument("--images", default="data/vision/images")
    ap.add_argument("--species-list", default="data/vision/species_list.json")
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--batch-size", type=int, default=96)
    ap.add_argument("--lr", type=float, default=3e-4)
    ap.add_argument("--embedding-size", type=int, default=256)
    ap.add_argument("--warmup-ratio", type=float, default=0.05)
    ap.add_argument("--max-species", type=int, default=0)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="data/vision/ft/dinov2-au")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.manual_seed(args.seed)

    species_list = {s["key"]: s for s in json.loads(Path(args.species_list).read_text())}
    ds = SpeciesImages(args.images, species_list, args.max_species, args.limit, args.seed)
    if len(ds) < 16:
        print("ERROR: too few images — check paths/max_species/limit", file=sys.stderr)
        return 1
    n_labels = len(ds.label_map)
    print(f"images={len(ds)} species={n_labels} device={device}")

    model_id, hidden = MODELS[args.model]
    if "siglip2" in args.model:
        trunk = AutoModel.from_pretrained(model_id).vision_model.to(device)
        proc = AutoProcessor.from_pretrained(model_id)
        size = proc.size.get("shortest_edge", 384)
    else:
        trunk = AutoModel.from_pretrained(model_id).to(device)
        proc = AutoProcessor.from_pretrained(model_id)
        size = proc.size.get("shortest_edge", 224)

    head = torch.nn.Sequential(
        torch.nn.Linear(hidden, 512), torch.nn.ReLU(),
        torch.nn.Linear(512, args.embedding_size),
    ).to(device)
    params = list(trunk.parameters()) + list(head.parameters())
    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=1e-4)
    steps_per_epoch = max(1, len(ds) // args.batch_size)
    total_steps = steps_per_epoch * args.epochs
    warmup = int(total_steps * args.warmup_ratio)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, s / warmup) if warmup else 1.0)

    miner = miners.MultiSimilarityMiner(epsilon=0.1)
    loss_fn = losses.MultiSimilarityLoss(alpha=2, beta=50, base=0.5)

    sampler = samplers.MPerClassSampler(
        ds.labels, m=min(4, n_labels), length_before_new_iter=len(ds))
    loader = DataLoader(ds, batch_size=args.batch_size, sampler=sampler,
                        num_workers=4, pin_memory=True, collate_fn=pil_collate)
    dl_iter = iter(loader)

    for epoch in range(args.epochs):
        trunk.train(); head.train()
        tot, n = 0.0, 0
        for step in range(steps_per_epoch):
            try:
                imgs, labels = next(dl_iter)
            except StopIteration:
                dl_iter = iter(loader)
                imgs, labels = next(dl_iter)
            imgs = proc(images=list(imgs), return_tensors="pt",
                        **(dict(padding=True) if "siglip2" in args.model else {})).to(device)
            labels = labels.to(device)
            opt.zero_grad()
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                if "siglip2" in args.model:
                    feats = trunk(pixel_values=imgs["pixel_values"]).pooler_output
                else:
                    feats = trunk(imgs["pixel_values"]).last_hidden_state[:, 0]
                emb = torch.nn.functional.normalize(head(feats), dim=1)
                hard = miner(emb, labels)
                loss = loss_fn(emb, labels, hard)
            loss.backward()
            opt.step(); sched.step()
            tot += loss.item(); n += 1
        print(f"epoch {epoch+1}/{args.epochs}: loss {tot/n:.4f} (lr {opt.param_groups[0]['lr']:.2e})", flush=True)

        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        torch.save({"trunk": trunk.state_dict(), "head": head.state_dict()},
                   out / f"checkpoint-{epoch+1}.pt")
        with open(out / "config.json", "w") as f:
            json.dump({"model": args.model, "embedding_size": args.embedding_size,
                       "epochs": args.epochs, "label_map": ds.label_map}, f, indent=2)
    print(f"saved: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
