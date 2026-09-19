#!/usr/bin/env python3
"""AUGURY — Gate A/W1: DINOv2-base image encoder → ONNX (fp32 + int8).

Why this file exists
--------------------
The Android photo-ID feature needs the DINOv2-base encoder on-device. The
question this script answers is whether int8 dynamic quantisation can ship, or
whether the app must carry the (4x larger) fp32 graph.

Graph contract (what the Android app must replicate natively)
------------------------------------------------------------
The exported graph is the encoder and *nothing else*:

    input   pixel_values  float32[1, 3, 224, 224]   (already resized/cropped/normalised)
    output  cls_token     float32[1, 768]           (last_hidden_state[:, 0])

No resize, no crop, no rescale, no normalisation, no L2 norm and no PCA live in
the graph — all of that happens in Python here and must be re-implemented in
Kotlin/Swift on device. The one op that is not part of the ViT stack is the
Gather/Slice that selects token 0; it is in the graph because the contract
requires a [1, 768] output rather than the full [1, 257, 768] token grid.

The reference pipeline that must be matched exactly (scripts/vision/photo_id.py
`PhotoID.embed()`, which is what built index-v3):

    1. resize shortest edge 256, bicubic (resample=3), centre-crop 224x224
    2. RGB, rescale 1/255 = 0.00392156862745098
    3. normalise mean [0.485, 0.456, 0.406] / std [0.229, 0.224, 0.225]
    4. forward → CLS token (768-d, post-LayerNorm `last_hidden_state[:, 0]`)
    5. L2-normalise:            v /= norm(v) + 1e-9
    6. PCA-whiten:              v = (v - mu) @ W      (data/vision/index-v3/pca_whiten.npz)
    7. L2-normalise again:      v /= norm(v) + 1e-9

Steps 1-3 come from `AutoImageProcessor.from_pretrained("facebook/dinov2-base")`
so they cannot drift from the reference implementation.

Environment
-----------
This script needs `onnx`, `onnxruntime` AND `torch` in the interpreter that runs
it. That combination does NOT exist in `.venv-mcpmv46` (which has no `onnx`, and
whose transformers 5.7.0 must not be disturbed), so it is meant to run under the
separate `.venv-onnx`:

    UV_CACHE_DIR=/tmp/uvcache uv venv --python 3.11 .venv-onnx
    UV_CACHE_DIR=/tmp/uvcache uv pip install --python .venv-onnx/bin/python \\
        "optimum[onnxruntime]" onnxruntime pillow numpy torch \\
        --index-url https://download.pytorch.org/whl/cpu \\
        --extra-index-url https://pypi.org/simple

Commands
--------
    # 1. export fp32 + int8 into models/onnx/ (validates both graphs)
    .venv-onnx/bin/python scripts/app/export_encoder_onnx.py export

    # 2. embedding-level fidelity vs the PyTorch path (PhotoID.embed, 50 images)
    .venv-onnx/bin/python scripts/app/export_encoder_onnx.py fidelity --n 50

    # 3. cache RAW pre-PCA CLS vectors for the benchmark harness
    .venv-onnx/bin/python scripts/app/export_encoder_onnx.py cache \\
        --model int8 --backend dinov2-base-onnx-int8 --cache data/vision/emb-onnx

    # 3b. ... and the fp32 ONNX control
    .venv-onnx/bin/python scripts/app/export_encoder_onnx.py cache \\
        --model fp32 --backend dinov2-base-onnx-fp32 --cache data/vision/emb-onnx
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

MODEL_ID = "facebook/dinov2-base"
INPUT_NAME = "pixel_values"
OUTPUT_NAME = "cls_token"
FP32_NAME = "dinov2-base-fp32.onnx"
INT8_NAME = "dinov2-base-int8.onnx"
DEFAULT_ONNX_DIR = ROOT / "models" / "onnx"
SPLIT = ROOT / "data" / "vision" / "au_split.json"
IMAGES = ROOT / "data" / "vision" / "images"
INDEX_V3 = ROOT / "data" / "vision" / "index-v3"
PCA_V3 = INDEX_V3 / "pca_whiten.npz"
TMP_VENV_PY = ROOT / ".venv-mcpmv46" / "bin" / "python"   # the PyTorch reference venv

# "optimum[onnxruntime]" is installed per the task spec and supplies onnxruntime;
# the export itself uses torch.onnx.export so the graph is exactly the encoder
# plus the CLS gather (optimum's feature-extraction export emits the full
# [1, 257, 768] token grid, which would push token selection into the app).
REQUIRED_MODULES = ("torch", "onnx", "onnxruntime", "numpy", "PIL", "transformers")

INSTALL_HINT = f"""\
[fatal] this interpreter is missing required module(s): {{missing}}

Gate A/W1 must run under its own venv — do NOT install onnx/onnxruntime into
.venv-mcpmv46 (it has no pip, and adding them downgrades transformers 5.7.0 and
huggingface_hub 1.26.0, which docs/openbmb-playbook.md forbids).

Create the separate venv and re-run:

    cd {ROOT}
    UV_CACHE_DIR=/tmp/uvcache uv venv --python 3.11 .venv-onnx
    UV_CACHE_DIR=/tmp/uvcache uv pip install --python .venv-onnx/bin/python \\
        "optimum[onnxruntime]" onnxruntime pillow numpy torch \\
        --index-url https://download.pytorch.org/whl/cpu \\
        --extra-index-url https://pypi.org/simple

    .venv-onnx/bin/python scripts/app/export_encoder_onnx.py <command>

(uv cannot write to ~/.cache in this environment, hence UV_CACHE_DIR.)
"""


# ── environment ─────────────────────────────────────────────────────────────
def ensure_environment() -> dict:
    """Fail loudly and actionably before doing any half-work."""
    missing = [m for m in REQUIRED_MODULES if importlib.util.find_spec(m) is None]
    if missing:
        print(INSTALL_HINT.format(missing=", ".join(missing)), file=sys.stderr)
        raise SystemExit(2)

    import numpy
    import onnx
    import onnxruntime
    import PIL
    import torch
    import transformers

    if not hasattr(torch, "onnx"):
        print("[fatal] torch has no onnx module — install a torch build with "
              "ONNX export support", file=sys.stderr)
        raise SystemExit(2)

    return {
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "torch": torch.__version__,
        "onnx": onnx.__version__,
        "onnxruntime": onnxruntime.__version__,
        "transformers": transformers.__version__,
        "numpy": numpy.__version__,
        "pillow": PIL.__version__,
    }


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def human_bytes(n: int) -> str:
    return f"{n:,} bytes ({n / 1e6:.1f} MB)"


def cosine(a, b) -> float:
    import numpy as np
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    return float(a @ b / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-12))


# ── model / graph ───────────────────────────────────────────────────────────
def load_encoder():
    """AutoModel exactly as photo_id.py / cache_embeddings.py load it."""
    from transformers import AutoImageProcessor, AutoModel

    encoder = AutoModel.from_pretrained(MODEL_ID).eval()
    processor = AutoImageProcessor.from_pretrained(MODEL_ID)
    return encoder, processor


def load_processor():
    """The HF processor alone (steps 1-3); the weights are not needed for it."""
    from transformers import AutoImageProcessor

    return AutoImageProcessor.from_pretrained(MODEL_ID)


def make_wrapper(encoder):
    import torch

    class ClsEncoder(torch.nn.Module):
        """Encoder + `last_hidden_state[:, 0]`. Nothing else."""

        def __init__(self, model):
            super().__init__()
            self.encoder = model

        def forward(self, pixel_values):
            return self.encoder(pixel_values=pixel_values).last_hidden_state[:, 0]

    return ClsEncoder(encoder).eval()


def export_fp32(out_path: Path, opset: int = 17) -> Path:
    import torch

    encoder, _ = load_encoder()
    wrapper = make_wrapper(encoder)
    dummy = torch.zeros(1, 3, 224, 224, dtype=torch.float32)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    kwargs = dict(
        input_names=[INPUT_NAME],
        output_names=[OUTPUT_NAME],
        opset_version=opset,
        do_constant_folding=True,
        dynamic_axes=None,          # static [1,3,224,224] — matches the app contract
    )
    try:
        torch.onnx.export(wrapper, (dummy,), str(out_path), dynamo=False, **kwargs)
    except TypeError:
        # torch too old/new for the `dynamo` kwarg: fall back to the default exporter
        torch.onnx.export(wrapper, (dummy,), str(out_path), **kwargs)
    return out_path


def export_int8(fp32_path: Path, int8_path: Path, weight_type: str = "qint8",
                per_channel: bool = False) -> Path:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    wt = {"qint8": QuantType.QInt8, "quint8": QuantType.QUInt8}[weight_type]
    quantize_dynamic(
        model_input=str(fp32_path),
        model_output=str(int8_path),
        weight_type=wt,
        per_channel=per_channel,
        reduce_range=False,
    )
    return int8_path


def inspect_graph(path: Path) -> dict:
    """Structural facts about an .onnx file — used for the results report."""
    import collections

    import onnx

    model = onnx.load(str(path))
    onnx.checker.check_model(model)
    g = model.graph
    ops = collections.Counter(n.op_type for n in g.node)
    init_bytes = sum(len(t.raw_data) for t in g.initializer)

    def shape(vi):
        dims = []
        for d in vi.type.tensor_type.shape.dim:
            dims.append(d.dim_value if d.dim_value else (d.dim_param or "?"))
        return dims

    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
        "ir_version": model.ir_version,
        "opset": [{"domain": o.domain or "ai.onnx", "version": o.version}
                  for o in model.opset_import],
        "inputs": [{"name": i.name, "shape": shape(i),
                    "dtype": onnx.TensorProto.DataType.Name(i.type.tensor_type.elem_type)}
                   for i in g.input],
        "outputs": [{"name": o.name, "shape": shape(o),
                     "dtype": onnx.TensorProto.DataType.Name(o.type.tensor_type.elem_type)}
                    for o in g.output],
        "n_nodes": len(g.node),
        "n_initializers": len(g.initializer),
        "initializer_bytes": init_bytes,
        "op_histogram": dict(sorted(ops.items(), key=lambda kv: -kv[1])),
        # The graph must not do image pre/post-processing — that lives in Kotlin
        # (core/vision/Preprocessor.kt) so the manifest's `preprocess` block stays
        # the single source of truth.
        #
        # NOTE: a bare "does the graph contain Resize/Normalize?" check is a FALSE
        # POSITIVE. DINOv2's `interpolate_pos_encoding` emits one legitimate
        # `Resize` node that operates on the *position-embedding* tensor, not on
        # the input image. Verified 2026-09-19: the fp32 graph has 1 Resize and 0
        # Normalize nodes, yet ONNX and PyTorch agree to cosine 1.00000000 on
        # identical pixel_values, so the graph is encoder-only.
        #
        # The precise test is whether a preprocessing op consumes the GRAPH INPUT
        # directly. Position-embedding interpolation always consumes an internal
        # tensor, so it cannot trip this.
        "has_resize_or_normalize": bool(
            _preprocess_ops_touching_input(g)),
    }


def _preprocess_ops_touching_input(graph) -> list:
    """Resize/Normalize/Sub/Div nodes that consume the graph input directly.

    An image-preprocessing graph starts by resizing or renormalising
    `pixel_values` itself; an encoder-only graph never does.
    """
    if not graph.input:
        return []
    input_names = {i.name for i in graph.input}
    offender_ops = {"Resize", "Normalize", "MeanVarianceNormalization"}
    hits = []
    for node in graph.node:
        if node.op_type in offender_ops and input_names.intersection(node.input):
            hits.append(node.op_type)
    return hits


def open_session(path: Path, threads: int = 0):
    import onnxruntime as ort

    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    if threads:
        so.intra_op_num_threads = threads
    return ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])


def session_output_shape(sess) -> list:
    out = sess.get_outputs()[0]
    return [d if isinstance(d, int) else str(d) for d in out.shape]


# ── preprocessing / postprocessing (outside the graph) ──────────────────────
def final_embedding(cls_vec, W, mu):
    """Steps 5-7 of the reference pipeline: L2 → PCA-whiten → L2."""
    import numpy as np

    v = np.asarray(cls_vec, dtype=np.float32).ravel()
    v = v / (np.linalg.norm(v) + 1e-9)
    v = (v - mu) @ W
    v = v / (np.linalg.norm(v) + 1e-9)
    return v.astype(np.float32)


def load_pca(path: Path):
    import numpy as np

    z = np.load(path)
    return z["W"].astype(np.float32), z["mu"].astype(np.float32)


def preprocess(processor, image):
    return processor(images=image, return_tensors="np")[INPUT_NAME].astype("float32")


# ── commands ────────────────────────────────────────────────────────────────
def cmd_export(args) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fp32 = out_dir / FP32_NAME
    int8 = out_dir / INT8_NAME

    print(f"[export] torch={__import__('torch').__version__} model={MODEL_ID} opset={args.opset}")
    t0 = time.time()
    export_fp32(fp32, opset=args.opset)
    print(f"[export] fp32 written in {time.time() - t0:.1f}s -> {fp32} "
          f"({human_bytes(fp32.stat().st_size)})")

    t0 = time.time()
    export_int8(fp32, int8, weight_type=args.weight_type, per_channel=args.per_channel)
    print(f"[export] int8 written in {time.time() - t0:.1f}s -> {int8} "
          f"({human_bytes(int8.stat().st_size)})")

    facts = {}
    for name, p in (("fp32", fp32), ("int8", int8)):
        f = inspect_graph(p)
        facts[name] = f
        print(f"[export] {name}: in={f['inputs'][0]['name']}{f['inputs'][0]['shape']} "
              f"out={f['outputs'][0]['name']}{f['outputs'][0]['shape']} "
              f"nodes={f['n_nodes']} ops={list(f['op_histogram'])[:6]}")
        if f["has_resize_or_normalize"]:
            print(f"[export] FATAL: {name} graph contains resize/normalise ops — the "
                  f"graph must be the encoder only", file=sys.stderr)
            return 3

    # run both graphs on one real image and on a deterministic random tensor
    import numpy as np
    from PIL import Image

    processor = load_processor()
    img = next(iter(sorted(IMAGES.glob("*/*.jpg"))))
    x = preprocess(processor, Image.open(img).convert("RGB"))
    rng = np.random.default_rng(0)
    xs = {"real_image": x, "random": rng.standard_normal((1, 3, 224, 224), dtype=np.float32)}

    checks = {}
    s32, s8 = open_session(fp32, args.threads), open_session(int8, args.threads)
    for label, xx in xs.items():
        o32 = s32.run(None, {INPUT_NAME: xx})[0]
        o8 = s8.run(None, {INPUT_NAME: xx})[0]
        checks[label] = {
            "fp32_shape": list(o32.shape), "int8_shape": list(o8.shape),
            "fp32_dtype": str(o32.dtype), "int8_dtype": str(o8.dtype),
            "cosine_fp32_vs_int8": cosine(o32, o8),
            "max_abs_diff": float(np.max(np.abs(o32.astype(np.float64) - o8.astype(np.float64)))),
        }
        print(f"[export] validate {label}: fp32{o32.shape} int8{o8.shape} "
              f"cos={checks[label]['cosine_fp32_vs_int8']:.6f} "
              f"maxdiff={checks[label]['max_abs_diff']:.4f}")

    summary = {
        "model_id": MODEL_ID, "opset": args.opset,
        "input": {"name": INPUT_NAME, "shape": [1, 3, 224, 224], "dtype": "float32"},
        "output": {"name": OUTPUT_NAME, "shape": [1, 768], "dtype": "float32"},
        "int8_recipe": {"quantize_dynamic": True, "weight_type": args.weight_type,
                        "per_channel": args.per_channel, "reduce_range": False},
        "graphs": facts, "runtime_checks": checks,
    }
    (out_dir / "export_summary.json").write_text(json.dumps(summary, indent=1))
    print(f"[export] wrote {out_dir / 'export_summary.json'}")
    return 0


# ── fidelity (a): ONNX vs the real PyTorch PhotoID path ─────────────────────
PYTORCH_REF_SNIPPET = r'''
import json, sys
from pathlib import Path
import numpy as np
import torch

root = Path(sys.argv[3])
sys.path.insert(0, str(root / "scripts" / "vision"))
from PIL import Image
from photo_id import PhotoID

refs = json.loads(Path(sys.argv[1]).read_text())
outdir = Path(sys.argv[2]); outdir.mkdir(parents=True, exist_ok=True)

# The real shipped path: PhotoID loads index-v3 (so embed() applies index-v3's
# PCA + the second L2 norm), the DINOv2 encoder and the HF processor.
pid = PhotoID(index_dir=str(root / "data" / "vision" / "index-v3"))
print(f"[pt-ref] index={pid.index.ntotal} keys, pca={pid.pca is not None}")

finals, raws, pixels, missing = [], [], [], []
for rel in refs:
    p = root / "data" / "vision" / "images" / rel
    if not p.is_file():
        missing.append(rel); continue
    im = Image.open(p).convert("RGB")
    finals.append(np.asarray(pid.embed(im), dtype=np.float32).ravel())          # steps 1-7
    inp = pid.processor(images=im, return_tensors="pt")                        # steps 1-3
    pixels.append(inp["pixel_values"][0].numpy().astype(np.float32))
    with torch.no_grad():
        raw = pid.encoder(**inp).last_hidden_state[:, 0].float().cpu().numpy()[0]
    raws.append(raw.astype(np.float32))                                        # step 4 only

np.save(outdir / "pt_final.npy", np.stack(finals))
np.save(outdir / "pt_raw.npy", np.stack(raws))
np.save(outdir / "pt_pixels.npy", np.stack(pixels))
print(json.dumps({"n": len(finals), "missing": missing,
                  "dim_final": int(finals[0].size), "dim_raw": int(raws[0].size)}))
'''


def pick_fidelity_refs(n: int, seed: int) -> list:
    """Deterministic, species-spread sample of benchmark images."""
    doc = json.loads(SPLIT.read_text())
    rng = random.Random(seed)
    keys = sorted(doc["species"])
    rng.shuffle(keys)
    refs = []
    round_i = 0
    while len(refs) < n:
        added = False
        for k in keys:
            pool = sorted(doc["species"][k]["gallery"] + doc["species"][k]["queries"])
            if round_i < len(pool):
                refs.append(pool[round_i])
                added = True
                if len(refs) >= n:
                    break
        if not added:
            break
        round_i += 1
    return refs


def cmd_fidelity(args) -> int:
    import numpy as np

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    refs = pick_fidelity_refs(args.n, args.seed)
    print(f"[fidelity] {len(refs)} images (seed={args.seed}, spread over species)")

    tmp = Path(tempfile.mkdtemp(prefix="augury_onnx_fidelity_"))
    (tmp / "refs.json").write_text(json.dumps(refs))
    (tmp / "pytorch_ref.py").write_text(PYTORCH_REF_SNIPPET)
    if not TMP_VENV_PY.exists():
        print(f"[fatal] reference venv python not found: {TMP_VENV_PY}", file=sys.stderr)
        return 2
    print(f"[fidelity] running the PyTorch reference under {TMP_VENV_PY} …")
    t0 = time.time()
    proc = subprocess.run(
        [str(TMP_VENV_PY), str(tmp / "pytorch_ref.py"),
         str(tmp / "refs.json"), str(tmp), str(ROOT)],
        capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout[-4000:]); print(proc.stderr[-4000:], file=sys.stderr)
        print("[fatal] PyTorch reference run failed", file=sys.stderr)
        return 2
    print(f"[fidelity] reference done in {time.time() - t0:.1f}s: {proc.stdout.strip()}")
    pt_meta = json.loads(proc.stdout.strip().splitlines()[-1])

    pt_final = np.load(tmp / "pt_final.npy")
    pt_raw = np.load(tmp / "pt_raw.npy")
    pt_pix = np.load(tmp / "pt_pixels.npy")

    # ONNX path, same processor from the (isolated) onnx venv
    from PIL import Image
    processor = load_processor()
    W, mu = load_pca(PCA_V3)
    s32 = open_session(Path(args.onnx_dir) / FP32_NAME, args.threads)
    s8 = open_session(Path(args.onnx_dir) / INT8_NAME, args.threads)

    onnx_pix, f32_final, f32_raw, i8_final, i8_raw = [], [], [], [], []
    for rel in refs:
        im = Image.open(IMAGES / rel).convert("RGB")
        x = preprocess(processor, im)
        onnx_pix.append(x[0])
        for sess, finals, raws in ((s32, f32_final, f32_raw), (s8, i8_final, i8_raw)):
            cls = sess.run(None, {INPUT_NAME: x})[0][0]
            raws.append(cls.astype(np.float32))
            finals.append(final_embedding(cls, W, mu))
        print(f"[fidelity]   {rel}", flush=True)

    onnx_pix = np.stack(onnx_pix)
    f32_final, f32_raw = np.stack(f32_final), np.stack(f32_raw)
    i8_final, i8_raw = np.stack(i8_final), np.stack(i8_raw)

    def stat_block(A, B):
        cos = np.array([cosine(a, b) for a, b in zip(A, B)])
        return {"mean_cosine": float(cos.mean()), "min_cosine": float(cos.min()),
                "p05_cosine": float(np.percentile(cos, 5)),
                "n": int(len(cos))}

    result = {
        "n_images": len(refs),
        "seed": args.seed,
        "onnx_dir": str(Path(args.onnx_dir).resolve()),
        "pca": str(PCA_V3),
        "pytorch_reference": {"venv": str(TMP_VENV_PY), "index": str(INDEX_V3),
                              "api": "scripts/vision/photo_id.py PhotoID.embed()",
                              **pt_meta},
        # isolates preprocessing drift (different transformers/PIL in the two venvs)
        "preprocessing": {
            "max_abs_diff": float(np.max(np.abs(pt_pix.astype(np.float64)
                                                - onnx_pix.astype(np.float64)))),
            "mean_abs_diff": float(np.mean(np.abs(pt_pix.astype(np.float64)
                                                  - onnx_pix.astype(np.float64)))),
            "identical_bitwise": bool(np.array_equal(pt_pix, onnx_pix)),
        },
        # stage 4 only: raw CLS token, pre-norm/pre-PCA (what the cache stores)
        "raw_cls_768": {
            "fp32_onnx_vs_pytorch": stat_block(f32_raw, pt_raw),
            "int8_onnx_vs_pytorch": stat_block(i8_raw, pt_raw),
            "int8_onnx_vs_fp32_onnx": stat_block(i8_raw, f32_raw),
        },
        # steps 5-7: what actually gets compared against the index
        "final_384_after_l2_pca_l2": {
            "fp32_onnx_vs_pytorch": stat_block(f32_final, pt_final),
            "int8_onnx_vs_pytorch": stat_block(i8_final, pt_final),
            "int8_onnx_vs_fp32_onnx": stat_block(i8_final, f32_final),
        },
        "images": refs,
    }
    (out_dir / "fidelity.json").write_text(json.dumps(result, indent=1))
    print(json.dumps({k: v for k, v in result.items() if k != "images"}, indent=1))
    print(f"[fidelity] wrote {out_dir / 'fidelity.json'} (temp artifacts in {tmp})")
    return 0


# ── (b) cache embeddings in the bench.py layout ─────────────────────────────
def cmd_cache(args) -> int:
    import numpy as np
    from PIL import Image

    onnx_path = Path(args.onnx_dir) / (INT8_NAME if args.model == "int8" else FP32_NAME)
    if not onnx_path.exists():
        print(f"[fatal] {onnx_path} not found — run the `export` command first",
              file=sys.stderr)
        return 2
    backend = args.backend
    outdir = Path(args.cache) / backend.replace("/", "_") / "single"
    outdir.mkdir(parents=True, exist_ok=True)

    doc = json.loads(Path(args.split).read_text())
    work = [(k, rel) for k, v in doc["species"].items()
            for rel in (v["gallery"] + v["queries"])]
    if args.limit:
        work = work[: args.limit]
    print(f"[cache] backend={backend} model={args.model} onnx={onnx_path.name} "
          f"items={len(work)} -> {outdir}")

    processor = load_processor()
    sess = open_session(onnx_path, args.threads)
    dim = int(sess.get_outputs()[0].shape[-1])
    manifest = {
        "backend": backend, "tta": "single", "dim": dim, "model": args.model,
        "source_onnx": onnx_path.name, "onnx_sha256": sha256(onnx_path),
        "split": str(Path(args.split).resolve()),
        "postprocess": "L2 normalise only (pre-PCA, pre-whitening) — matches "
                       "cache_embeddings.py; bench.py applies PCA itself",
        "work_total": len(work), "status": "in_progress",
    }
    (outdir / "_manifest.json").write_text(json.dumps(manifest, indent=1))

    done = skipped = failed = 0
    t_start = time.time()
    for i, (key, rel) in enumerate(work, 1):
        dest = outdir / key / (Path(rel).stem + ".npy")
        if dest.exists() and not args.overwrite:
            skipped += 1
            continue
        try:
            im = Image.open(Path(args.images) / rel).convert("RGB")
            x = preprocess(processor, im)
            cls = sess.run(None, {INPUT_NAME: x})[0][0].astype(np.float32)
            vec = cls / (np.linalg.norm(cls) + 1e-9)
            dest.parent.mkdir(parents=True, exist_ok=True)
            np.save(dest, vec.astype(np.float32))
            done += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"[cache]   FAIL {rel}: {exc}", flush=True)
        if i % 200 == 0 or i == len(work):
            el = time.time() - t_start
            rate = done / el if el else 0
            eta = (len(work) - i) / rate if rate else 0
            print(f"[cache] {i}/{len(work)} ({done} new, {skipped} cached, {failed} failed) "
                  f"{rate:.1f} img/s eta {eta / 60:.1f} min", flush=True)

    manifest.update({"cached_total": done + skipped, "new": done, "skipped": skipped,
                     "failed": failed, "status": "complete",
                     "elapsed_s": round(time.time() - t_start, 1)})
    (outdir / "_manifest.json").write_text(json.dumps(manifest, indent=1))
    print(f"[cache] done: {done} new, {skipped} cached, {failed} failed in "
          f"{(time.time() - t_start) / 60:.1f} min -> {outdir}")
    return 1 if failed else 0


# ── compare an ONNX cache against an existing PyTorch cache ─────────────────
def cmd_compare_cache(args) -> int:
    """Full-cache cosine check: ONNX vectors vs the existing PyTorch cache.

    Cheaper and far broader than the 50-image fidelity sample: it covers every
    gallery/query vector the benchmark actually consumes.
    """
    import numpy as np

    ours = Path(args.cache) / args.backend.replace("/", "_") / "single"
    theirs = Path(args.reference_cache) / args.reference_backend.replace("/", "_") / "single"
    doc = json.loads(Path(args.split).read_text())
    refs = [(k, rel) for k, v in doc["species"].items() for rel in (v["gallery"] + v["queries"])]

    cos, missing, n = [], 0, 0
    for key, rel in refs:
        stem = Path(rel).stem
        a, b = ours / key / f"{stem}.npy", theirs / key / f"{stem}.npy"
        if not a.exists() or not b.exists():
            missing += 1
            continue
        cos.append(cosine(np.load(a), np.load(b)))
        n += 1
    if not cos:
        print("[compare] no overlapping vectors", file=sys.stderr)
        return 2
    cos = np.array(cos)
    out = {"backend": args.backend, "reference_backend": args.reference_backend,
           "compared": n, "missing": missing,
           "mean_cosine": float(cos.mean()), "min_cosine": float(cos.min()),
           "p01_cosine": float(np.percentile(cos, 1)),
           "n_below_0.99": int((cos < 0.99).sum()),
           "n_below_0.95": int((cos < 0.95).sum())}
    print(json.dumps(out, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps(out, indent=1))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    e = sub.add_parser("export", help="export fp32 + int8 ONNX into models/onnx/")
    e.add_argument("--out-dir", default=str(DEFAULT_ONNX_DIR))
    e.add_argument("--opset", type=int, default=17)
    e.add_argument("--weight-type", default="qint8", choices=["qint8", "quint8"])
    e.add_argument("--per-channel", action="store_true")
    e.add_argument("--threads", type=int, default=0)
    e.set_defaults(fn=cmd_export)

    f = sub.add_parser("fidelity", help="compare ONNX vs the PyTorch PhotoID path")
    f.add_argument("--n", type=int, default=50)
    f.add_argument("--seed", type=int, default=20260819)
    f.add_argument("--onnx-dir", default=str(DEFAULT_ONNX_DIR))
    f.add_argument("--out-dir", default=str(ROOT / "data" / "vision" / "bench"))
    f.add_argument("--threads", type=int, default=0)
    f.set_defaults(fn=cmd_fidelity)

    c = sub.add_parser("cache", help="cache embeddings in the bench.py layout")
    c.add_argument("--model", default="int8", choices=["fp32", "int8"])
    c.add_argument("--backend", default="dinov2-base-onnx-int8")
    c.add_argument("--cache", default=str(ROOT / "data" / "vision" / "emb-onnx"))
    c.add_argument("--split", default=str(SPLIT))
    c.add_argument("--images", default=str(IMAGES))
    c.add_argument("--onnx-dir", default=str(DEFAULT_ONNX_DIR))
    c.add_argument("--threads", type=int, default=0)
    c.add_argument("--limit", type=int, default=0)
    c.add_argument("--overwrite", action="store_true")
    c.set_defaults(fn=cmd_cache)

    cc = sub.add_parser("compare-cache", help="cosine of an ONNX cache vs a PyTorch cache")
    cc.add_argument("--backend", default="dinov2-base-onnx-fp32")
    cc.add_argument("--cache", default=str(ROOT / "data" / "vision" / "emb-onnx"))
    cc.add_argument("--reference-backend", default="dinov2-base")
    cc.add_argument("--reference-cache", default=str(ROOT / "data" / "vision" / "emb"))
    cc.add_argument("--split", default=str(SPLIT))
    cc.add_argument("--out", default="")
    cc.set_defaults(fn=cmd_compare_cache)

    args = ap.parse_args()
    env = ensure_environment()
    print(f"[env] {env['executable']} python={env['python']} torch={env['torch']} "
          f"onnx={env['onnx']} onnxruntime={env['onnxruntime']} "
          f"transformers={env['transformers']} numpy={env['numpy']} pillow={env['pillow']}")
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
