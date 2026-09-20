#!/usr/bin/env python3
"""AUGURY — emit_vision_fixtures.py

Generate the host-verified fixture for the Kotlin vision path
(``augury-android/app/src/main/java/au/org/regeneratus/augury/vision``).

Why this exists
---------------
The Kotlin vision path must reproduce, bit-for-bit-ish, what the Python reference
does today (``scripts/vision/photo_id.py``):

    image -> preprocess -> ONNX CLS (768-d) -> L2 -> PCA-whiten -> L2 -> kNN(IP)

The Kotlin code cannot be executed against the real ONNX model or the real
gallery on this host (ONNX Runtime Mobile ships Android ``.so`` files only), so
this script runs the **real** model and the **real** index in Python, records
every intermediate, and the Kotlin unit test replays the same pipeline from the
recorded CLS token — and, for the pixel path, from the same JPEG.

What is recorded
----------------
* ``vision/query.jpg`` — a real held-out query photo from ``data/vision/au_split.json``
  that is **not** in the gallery (so the top-3 is a genuine retrieval result, not
  a self-match).
* ``vision/query_resized_crop_rgb.u8`` — the reference preprocessing result,
  HWC RGB uint8 224x224, i.e. what the ``transformers`` DINOv2 processor feeds
  the graph after resize + center crop (before /255 and normalisation).
* ``vision/pipeline_fixture.json`` — the reference CLS token, the whitened query,
  the 12 raw neighbours, the collapsed top-3, the band verdict, and the manifest
  values that produced them.

Determinism
-----------
Candidate queries are visited in sorted order; the first one that satisfies the
selection criteria wins.  Re-running on the same repo state reproduces the same
fixture.

Run:
    .venv-mcpmv46/bin/python augury-android/tools/emit_vision_fixtures.py
    .venv-mcpmv46/bin/python augury-android/tools/emit_vision_fixtures.py \
        --check-tensor app/build/vision-verify/kotlin_preprocessed.f32

``--check-tensor`` is the closing half of the cross-check: it feeds a tensor
produced by the **Kotlin** ``Preprocessor`` through the real ONNX model and
reports how far the resulting query vector and top-3 are from the reference.
Nothing is written in that mode unless ``--write-check`` is passed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ANDROID_ROOT = HERE.parent
REPO_ROOT = ANDROID_ROOT.parent

INDEX_DIR = REPO_ROOT / "data" / "vision" / "index-v3"
MANIFEST = REPO_ROOT / "data" / "app" / "manifest.json"
SPLIT = REPO_ROOT / "data" / "vision" / "au_split.json"
IMAGES = REPO_ROOT / "data" / "vision" / "images"
MODEL = REPO_ROOT / "models" / "onnx" / "dinov2-base-fp32.onnx"
OUT_DIR = ANDROID_ROOT / "app" / "src" / "test" / "resources" / "vision"

MAX_IMAGE_BYTES = 400_000
MAX_CANDIDATES = 60
EPS = 1e-9


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def l2(v: np.ndarray) -> np.ndarray:
    """photo_id.embed() step: vec /= (norm(vec) + 1e-9)."""
    return v / (np.linalg.norm(v) + EPS)


def pca_whiten(vec768: np.ndarray, W: np.ndarray, mu: np.ndarray) -> np.ndarray:
    """photo_id.embed() steps 3-5, exactly: (vec - mu) @ W, then L2 again."""
    return l2((l2(vec768) - mu) @ W)


def resize_shortest_edge(size: tuple[int, int], shortest: int) -> tuple[int, int]:
    """HF get_resize_output_image_size: shortest edge -> `shortest`, aspect kept,
    int() truncation.  size is (width, height)."""
    w, h = size
    if w <= h:
        return shortest, int(shortest * h / w)
    return int(shortest * w / h), shortest


def cubic(x: np.ndarray, a: float = -0.5) -> np.ndarray:
    x = np.abs(x)
    x2, x3 = x * x, x * x * x
    return np.where(
        x <= 1, (a + 2) * x3 - (a + 3) * x2 + 1,
        np.where(x < 2, a * x3 - 5 * a * x2 + 8 * a * x - 4 * a, 0.0),
    )


def resample_weights(in_size: int, out_size: int) -> np.ndarray:
    """Dense (out,in) weights for ATen's antialiased bicubic (align_corners=False).

    Verified against ``torchvision.transforms.v2.functional.resize`` on float32
    input to <=2.1e-05 max abs error on a 500x334 -> 383x256 resize (see
    docs/vision-kotlin-verification.md).  Kotlin ports exactly this function.
    """
    scale = in_size / out_size
    M = np.zeros((out_size, in_size), dtype=np.float64)
    for o in range(out_size):
        center = (o + 0.5) * scale - 0.5
        support = 2.0 * scale if scale >= 1.0 else 2.0
        start = int(np.floor(center - support)) + 1
        end = int(np.ceil(center + support)) - 1
        xs = np.arange(start, end + 1)
        arg = (xs - center) / scale if scale >= 1.0 else xs - center
        w = cubic(arg)
        keep = (xs >= 0) & (xs < in_size)
        xs, w = xs[keep], w[keep]
        M[o, xs] = w / w.sum()
    return M


def resize_model(rgb_u8: np.ndarray, nw: int, nh: int) -> np.ndarray:
    """Separable float AA-bicubic; returns float64 (nh,nw,3), unclamped."""
    Mh = resample_weights(rgb_u8.shape[0], nh)
    Mw = resample_weights(rgb_u8.shape[1], nw)
    out = np.tensordot(Mh, rgb_u8.astype(np.float64), axes=([1], [0]))
    return np.moveaxis(np.tensordot(out, Mw.T, axes=([1], [0])), 1, 2)


def normalize(u8_hwc: np.ndarray, mean, std) -> np.ndarray:
    """x/255 -> (x - mean)/std, CHW float32, exactly as the manifest declares."""
    f = u8_hwc.astype(np.float32) / 255.0
    f = (f - np.asarray(mean, np.float32)) / np.asarray(std, np.float32)
    return np.ascontiguousarray(np.transpose(f, (2, 0, 1)))


def centre_crop_origin(w: int, h: int, crop: int) -> tuple[int, int]:
    """transformers center_crop: crop_top = int((h - crop)/2.0); left likewise."""
    return int((w - crop) / 2.0), int((h - crop) / 2.0)


def collapse_top3(scores: np.ndarray, keys: list[str], k: int = 3,
                  canonical: dict | None = None) -> list[dict]:
    """Full collapse: best score per canonical key, then top-k.

    This is the semantics the Kotlin ``KnnIndex`` implements.  It is a superset
    of photo_id.identify(), which collapses only the first ``k*4`` neighbours;
    ``compare_collapse_semantics`` below checks the two agree on the fixture.
    """
    canonical = canonical or {}
    best: dict[str, dict] = {}
    for idx in np.argsort(-scores):
        key = keys[int(idx)]
        canon = canonical.get(key, key)
        s = float(scores[int(idx)])
        if canon not in best:
            best[canon] = {"key": key, "canonical": canon, "score": s, "index": int(idx)}
    return [best[c] for c in sorted(best, key=lambda c: -best[c]["score"])[:k]]


def collapse_top3_reference(scores: np.ndarray, keys: list[str], k: int = 3,
                            canonical: dict | None = None) -> list[dict]:
    """photo_id.identify(): search k*4 neighbours, de-duplicate canonical keys."""
    canonical = canonical or {}
    n = min(max(k * 4, k), len(scores))
    order = np.argsort(-scores)[:n]
    out, seen = [], set()
    for idx in order:
        key = keys[int(idx)]
        canon = canonical.get(key, key)
        if canon in seen:
            continue
        seen.add(canon)
        out.append({"key": key, "canonical": canon, "score": float(scores[int(idx)]),
                    "index": int(idx)})
        if len(out) >= k:
            break
    return out


def band_verdict(top1: float, bands: dict) -> str:
    auto = bands["auto_conf"]
    confirm = bands["confirm_conf"]
    return "auto" if top1 >= auto else "confirm" if top1 >= confirm else "unknown"


def synthetic_kernel_check(mean, std) -> dict:
    """A small synthetic image, resized by torchvision's float path.

    This is the sharp kernel test: a real photo comparison is limited by
    torchvision's int16 fixed-point uint8 kernel (up to 4 LSB), so a separate
    fixture records the *float* reference for a deterministic 71x53 pattern,
    which the Kotlin resampler must reproduce to ~1e-4.

    Parameters: shortest_edge 32, crop 16 (deliberately different from the
    manifest's 256/224 so the test cannot accidentally read the wrong values).
    """
    import torch
    import torchvision.transforms.v2.functional as tvF
    from torchvision.transforms.v2.functional import InterpolationMode

    shortest, crop = 32, 16
    rng = np.random.default_rng(20260920)
    rgb = rng.integers(0, 256, size=(53, 71, 3)).astype(np.uint8)   # H=53, W=71
    nw, nh = resize_shortest_edge((71, 53), shortest)               # -> (42, 32)
    t = torch.from_numpy(rgb.copy()).permute(2, 0, 1).unsqueeze(0).float()
    resized = tvF.resize(t, [nh, nw], interpolation=InterpolationMode.BICUBIC,
                         antialias=True)[0].permute(1, 2, 0).numpy().astype(np.float32)
    u8 = np.clip(np.floor(resized + 0.5), 0, 255).astype(np.uint8)
    cx, cy = centre_crop_origin(nw, nh, crop)
    crop_u8 = u8[cy:cy + crop, cx:cx + crop, :]
    tensor = normalize(crop_u8, mean, std).astype(np.float32)

    (OUT_DIR / "synthetic_rgb.u8").write_bytes(rgb.tobytes())
    (OUT_DIR / "synthetic_resized_float.f32").write_bytes(resized.astype("<f4").tobytes())
    (OUT_DIR / "synthetic_crop_rgb.u8").write_bytes(crop_u8.tobytes())
    print(f"synthetic    : {71}x{53} -> {nw}x{nh}, crop origin ({cx},{cy}), "
          f"float resize range [{resized.min():.3f}, {resized.max():.3f}]")
    return {
        "source": "torchvision.transforms.v2.functional.resize(float32, BICUBIC, antialias=True)",
        "settings": {"resize_shortest_edge": shortest, "crop": crop},
        "image": {"file": "vision/synthetic_rgb.u8", "width": 71, "height": 53,
                  "seed": 20260920, "generator": "numpy default_rng(20260920).integers(0,256)"},
        "resized_size": [int(nw), int(nh)],
        "crop_origin": [int(cx), int(cy)],
        "resized_float_file": "vision/synthetic_resized_float.f32",
        "crop_u8_file": "vision/synthetic_crop_rgb.u8",
        "crop_u8_sha256": sha256_file(OUT_DIR / "synthetic_crop_rgb.u8"),
        "tensor": [float(v) for v in tensor.reshape(-1)],
    }


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #

def build(args) -> int:
    import onnxruntime as ort
    from PIL import Image
    from transformers import AutoImageProcessor

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    manifest = json.loads(MANIFEST.read_text())
    vision = manifest["vision"]
    pre = vision["preprocess"]
    bands = vision["bands"]
    crop = int(pre["crop"])
    shortest = int(pre["resize_shortest_edge"])
    mean, std = pre["mean"], pre["std"]

    E = np.load(INDEX_DIR / "embeddings.npy")
    keys = json.loads((INDEX_DIR / "keys.json").read_text())
    npz = np.load(INDEX_DIR / "pca_whiten.npz")
    W = npz["W"].astype(np.float32)
    mu = npz["mu"].astype(np.float32)
    assert E.shape == (len(keys), W.shape[1]), (E.shape, len(keys), W.shape)
    unique_keys = sorted(set(keys))
    print(f"index: {E.shape[0]} vectors x {E.shape[1]}-d, {len(unique_keys)} species")

    canonical_path = REPO_ROOT / "data" / "vision" / "canonical_map.json"
    canonical = json.loads(canonical_path.read_text()).get("canonical", {})
    # v3 stores canonical labels already; assert rather than assume.
    sources_in_index = sorted(set(keys) & set(canonical))
    if sources_in_index:
        print(f"WARNING: {len(sources_in_index)} canonical-map sources are index keys: "
              f"{sources_in_index[:3]}")

    processor = AutoImageProcessor.from_pretrained("facebook/dinov2-base")
    assert int(processor.size["shortest_edge"]) == shortest, processor.size
    assert int(processor.crop_size["height"]) == crop == int(processor.crop_size["width"])
    assert list(processor.image_mean) == list(mean)
    assert list(processor.image_std) == list(std)

    sess = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    out_name = sess.get_outputs()[0].name
    in_shape = sess.get_inputs()[0].shape
    out_shape = sess.get_outputs()[0].shape

    split = json.loads(SPLIT.read_text())
    candidates = []
    for species, entry in sorted(split["species"].items()):
        for rel in entry["queries"]:
            p = IMAGES / rel
            if p.is_file() and p.stat().st_size <= MAX_IMAGE_BYTES:
                candidates.append((species, rel, p))
    print(f"candidates: {len(candidates)} on-disk queries <= {MAX_IMAGE_BYTES} B")

    chosen = None
    stats = []
    for species, rel, path in candidates[:MAX_CANDIDATES]:
        image = Image.open(path).convert("RGB")
        ref_tensor = processor(image, return_tensors="np")["pixel_values"]
        cls = sess.run([out_name], {in_name: ref_tensor})[0][0].astype(np.float32)
        q = pca_whiten(cls, W, mu)
        scores = E @ q
        ref3 = collapse_top3_reference(scores, keys, 3, canonical)
        full3 = collapse_top3(scores, keys, 3, canonical)
        same = [(c["key"], round(c["score"], 6)) for c in ref3] == \
               [(c["key"], round(c["score"], 6)) for c in full3]
        ok = (ref3 and ref3[0]["canonical"] == species and ref3[0]["score"] >= bands["auto_conf"]
              and same and len({c["canonical"] for c in ref3}) == 3)
        stats.append((species, rel, ref3[0]["score"] if ref3 else -1, ok, same))
        if ok and chosen is None:
            chosen = (species, rel, path, image, ref_tensor, cls, q, scores, ref3, full3)
            break

    if chosen is None:
        print("no candidate satisfied the selection criteria; last 10:")
        for s in stats[-10:]:
            print("   ", s)
        return 1

    species, rel, path, image, ref_tensor, cls, q, scores, ref3, full3 = chosen
    print(f"chosen query : {rel} ({species})  {image.size}, {path.stat().st_size} B")

    # --- preprocessing intermediates -----------------------------------------
    rgb_u8 = np.asarray(image)
    nw, nh = resize_shortest_edge(image.size, shortest)
    float_model = resize_model(rgb_u8, nw, nh)
    # torchvision casts back to uint8 for a uint8 input: clamp then round.
    model_u8_full = np.clip(np.round(float_model), 0, 255).astype(np.uint8)
    cx, cy = centre_crop_origin(nw, nh, crop)
    model_crop = model_u8_full[cy:cy + crop, cx:cx + crop, :]
    # The processor's pixel_values are *normalised*; to capture the uint8
    # intermediate the reference actually resizes, drive the processor's own
    # resize/center_crop steps (the same methods _preprocess calls).
    import torchvision.transforms.v2.functional as tvF
    batch = tvF.pil_to_tensor(image).unsqueeze(0)
    resized_ref = processor.resize(batch, size=processor.size, resample=processor.resample)
    ref_u8 = np.transpose(processor.center_crop(resized_ref, processor.crop_size)[0].numpy(),
                          (1, 2, 0))

    delta = np.abs(model_crop.astype(np.int32) - ref_u8.astype(np.int32))
    kernel_delta = {
        "max_lsb": int(delta.max()),
        "exact_fraction": float((delta == 0).mean()),
        "within_1_fraction": float((delta <= 1).mean()),
        "mean_abs_lsb": float(delta.mean()),
        "note": ("difference between a float AA-bicubic kernel (what Kotlin "
                 "implements) and torchvision's int16 fixed-point uint8 kernel "
                 "(what the transformers reference uses)"),
    }
    print(f"kernel delta : max {kernel_delta['max_lsb']} LSB, exact "
          f"{kernel_delta['exact_fraction']:.4f}, within1 "
          f"{kernel_delta['within_1_fraction']:.4f}, mean {kernel_delta['mean_abs_lsb']:.4f}")

    # end-to-end effect of that delta: run the real model on the float-model crop
    alt_tensor = normalize(model_crop, mean, std)[None, ...]
    cls_alt = sess.run([out_name], {in_name: alt_tensor.astype(np.float32)})[0][0].astype(np.float32)
    q_alt = pca_whiten(cls_alt, W, mu)
    scores_alt = E @ q_alt
    alt3 = collapse_top3(scores_alt, keys, 3, canonical)
    print(f"kernel delta -> cls cosine {float(l2(cls) @ l2(cls_alt)):.8f}, top1 {alt3[0]['score']:.5f} "
          f"(ref {ref3[0]['score']:.5f})")

    # --- faiss cross-check (the reference ships a faiss index) ---------------
    faiss_ok = None
    try:
        import faiss
        fidx = faiss.read_index(str(INDEX_DIR / "index.faiss"))
        fs, fi = fidx.search(q.reshape(1, -1), 12)
        faiss_ok = bool(np.allclose(fs[0], np.sort(scores)[::-1][:12], atol=1e-5)
                        and set(fi[0].tolist()) == set(np.argsort(-scores)[:12].tolist()))
        print(f"faiss vs numpy top-12 identical: {faiss_ok}")
    except Exception as exc:  # noqa: BLE001
        print(f"faiss cross-check skipped: {exc!r}")

    # --- write fixture --------------------------------------------------------
    img_name = "query.jpg"
    rgb_name = "query_rgb.u8"
    (OUT_DIR / img_name).write_bytes(path.read_bytes())
    (OUT_DIR / rgb_name).write_bytes(rgb_u8.tobytes())          # PIL's decoded pixels
    (OUT_DIR / "query_resized_crop_rgb.reference.u8").write_bytes(ref_u8.tobytes())

    sample_idx = list(range(0, crop * crop * 3, max(1, (crop * crop * 3) // 512)))[:512]
    ref_tensor_chw = ref_tensor[0].astype(np.float32)
    flat = ref_tensor_chw.reshape(-1)
    fixture = {
        "kind": "augury.vision.pipeline_fixture",
        "schema": 1,
        "generated_by": "augury-android/tools/emit_vision_fixtures.py",
        "image": {
            "resource": f"vision/{img_name}",
            "source_path": str(path.relative_to(REPO_ROOT)),
            "sha256": sha256_file(path),
            "width": int(image.size[0]),
            "height": int(image.size[1]),
            "ground_truth_key": species,
            "in_gallery": False,
        },
        "manifest": {
            "path": str(MANIFEST.relative_to(REPO_ROOT)),
            "sha256": sha256_file(MANIFEST),
            "protocol": vision["index"]["protocol"],
            "preprocess": pre,
            "bands": bands,
        },
        "encoder": {
            "model": str(MODEL.relative_to(REPO_ROOT)),
            "input_name": in_name,
            "input_shape": list(in_shape),
            "output_name": out_name,
            "output_shape": [int(out_shape[0]) if isinstance(out_shape[0], int) else out_shape[0],
                             int(out_shape[1])],
        },
        "index": {
            "dir": str(INDEX_DIR.relative_to(REPO_ROOT)),
            "vectors": int(E.shape[0]),
            "dim": int(W.shape[1]),
            "cls_dim": int(W.shape[0]),
            "species": len(unique_keys),
            "canonical_sources_in_index": sources_in_index,
            "pca": {
                "file": "pca_whiten.npz",
                "W_shape": list(W.shape),
                "mu_shape": list(mu.shape),
                "dim": int(npz["dim"]),
                "whiten": float(npz["whiten"]),
            },
            "faiss_matches_numpy_top12": faiss_ok,
        },
        "cls_token": [float(v) for v in cls],
        "cls_token_alt_kernel": [float(v) for v in cls_alt],
        "query_whitened": [float(v) for v in q],
        "top_raw": [
            {"index": int(i), "key": keys[int(i)], "score": float(scores[int(i)])}
            for i in np.argsort(-scores)[:12]
        ],
        "top3": ref3,
        "top3_full_collapse": full3,
        "band": {
            "auto_conf": bands["auto_conf"],
            "confirm_conf": bands["confirm_conf"],
            "verdict": band_verdict(ref3[0]["score"], bands),
        },
        "preprocess_check": {
            "resized_size": [int(nw), int(nh)],
            "crop_origin": [int(cx), int(cy)],
            "rgb_file": f"vision/{rgb_name}",
            "rgb_sha256": sha256_file(OUT_DIR / rgb_name),
            "reference_u8_file": "vision/query_resized_crop_rgb.reference.u8",
            "reference_u8_sha256": sha256_file(OUT_DIR / "query_resized_crop_rgb.reference.u8"),
            "kernel_delta": kernel_delta,
            "sample_indices": sample_idx,
            "sample_values": [float(flat[i]) for i in sample_idx],
            "tensor_min": float(ref_tensor_chw.min()),
            "tensor_max": float(ref_tensor_chw.max()),
            "tensor_mean": [float(ref_tensor_chw.mean()) for c in range(3)],
            "alt_kernel_top3": alt3,
            "alt_kernel_cls_cosine": float(l2(cls) @ l2(cls_alt)),
        },
        "synthetic_kernel_check": synthetic_kernel_check(mean, std),
    }
    out_json = OUT_DIR / "pipeline_fixture.json"
    out_json.write_text(json.dumps(fixture, indent=1) + "\n")
    print(f"wrote {out_json.relative_to(REPO_ROOT)} ({out_json.stat().st_size} B), "
          f"{rgb_name} ({(OUT_DIR / rgb_name).stat().st_size} B), {img_name} "
          f"({(OUT_DIR / img_name).stat().st_size} B)")
    print("reference top-3:")
    for c in ref3:
        print(f"   {c['canonical']:<28s} key={c['key']:<28s} score={c['score']:.6f}")
    print(f"verdict: {fixture['band']['verdict']} (auto>={bands['auto_conf']}, "
          f"confirm>={bands['confirm_conf']})")
    return 0


def check_tensor(args) -> int:
    """Feed a Kotlin-produced NCHW float32 tensor through the real ONNX model."""
    import onnxruntime as ort

    fixture = json.loads((OUT_DIR / "pipeline_fixture.json").read_text())
    pre = fixture["manifest"]["preprocess"]
    crop = int(pre["crop"])
    raw = Path(args.check_tensor).read_bytes()
    tensor = np.frombuffer(raw, dtype="<f4")
    expect = 3 * crop * crop
    if tensor.size != expect:
        print(f"expected {expect} float32 values ({3}x{crop}x{crop}), got {tensor.size}")
        return 1
    tensor = tensor.reshape(1, 3, crop, crop)

    E = np.load(INDEX_DIR / "embeddings.npy")
    keys = json.loads((INDEX_DIR / "keys.json").read_text())
    npz = np.load(INDEX_DIR / "pca_whiten.npz")
    W = npz["W"].astype(np.float32)
    mu = npz["mu"].astype(np.float32)
    canonical = json.loads((REPO_ROOT / "data" / "vision" / "canonical_map.json").read_text()) \
        .get("canonical", {})

    sess = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
    in_name = sess.get_inputs()[0].name
    out_name = sess.get_outputs()[0].name
    cls = sess.run([out_name], {in_name: tensor.astype(np.float32)})[0][0].astype(np.float32)
    q = pca_whiten(cls, W, mu)
    scores = E @ q
    top3 = collapse_top3(scores, keys, 3, canonical)

    ref_cls = np.asarray(fixture["cls_token"], dtype=np.float32)
    ref_q = np.asarray(fixture["query_whitened"], dtype=np.float32)
    ref3 = fixture["top3"]
    ref_scores = np.asarray([c["score"] for c in ref3], dtype=np.float64)
    got_scores = np.asarray([c["score"] for c in top3], dtype=np.float64)

    ref_top1_index = int(np.argmax(E @ ref_q))
    order = np.argsort(-scores)
    rank = int(np.where(order == ref_top1_index)[0][0]) if ref_top1_index in order else -1

    report = {
        "kotlin_tensor": str(args.check_tensor),
        "cls_max_abs_delta": float(np.abs(cls - ref_cls).max()),
        "cls_cosine": float(l2(cls) @ l2(ref_cls)),
        "query_max_abs_delta": float(np.abs(q - ref_q).max()),
        "query_cosine": float(l2(q) @ l2(ref_q)),
        "reference_top3": [{"key": c["key"], "score": c["score"]} for c in ref3],
        "kotlin_top3": [{"key": c["key"], "score": c["score"]} for c in top3],
        "keys_match": [c["key"] for c in ref3] == [c["key"] for c in top3],
        "max_score_delta": float(np.abs(ref_scores - got_scores).max()),
        "reference_top1_rank_in_kotlin_scores": rank,
    }
    print(json.dumps(report, indent=1))
    if args.write_check:
        path = Path(args.write_check)
        path.write_text(json.dumps(report, indent=1) + "\n")
        print(f"wrote {path}")
    return 0 if report["keys_match"] else 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check-tensor", metavar="FILE",
                    help="NCHW float32 tensor written by the Kotlin Preprocessor")
    ap.add_argument("--write-check", metavar="FILE",
                    help="with --check-tensor: also write the comparison report here")
    args = ap.parse_args()
    if args.check_tensor:
        return check_tensor(args)
    return build(args)


if __name__ == "__main__":
    sys.exit(main())
