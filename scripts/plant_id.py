#!/usr/bin/env python3
"""
AUGURY Plant Identification Clients.

Primary: iNaturalist Computer Vision API (free, unlimited, no API key)
Fallback: PlantNet API (500 free/day, needs API key + attribution)

Usage:
    from plant_id import identify_plant
    result = identify_plant(image_bytes)  # uses iNaturalist by default
    result = identify_plant(image_bytes, service="plantnet", api_key="...")
"""

import requests
import base64
from io import BytesIO


# ── iNaturalist client ───────────────────────────────────────

INAT_URL = "https://api.inaturalist.org/v1/computervision/score_image"


def identify_inaturalist(image_bytes, top_n=5):
    """
    Identify plant species from image using iNaturalist Computer Vision API.

    Free, no API key, no attribution required.
    Rate limited by IP (~100 req/min).
    Response time: 1-3 seconds.

    Args:
        image_bytes: Raw image bytes (JPEG/PNG).
        top_n: Max results to return (default 5).

    Returns:
        List of dicts: [{scientific_name, common_name, score, taxon_id}, ...]
        OR empty list on error.
    """
    try:
        resp = requests.post(
            INAT_URL,
            files={"image": ("weed.jpg", BytesIO(image_bytes), "image/jpeg")},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for r in data.get("results", [])[:top_n]:
            results.append({
                "scientific_name": r["taxon"]["name"],
                "common_name": r["taxon"].get("preferred_common_name", ""),
                "score": round(r["score"], 4),
                "taxon_id": r["taxon"]["id"],
            })

        return results

    except requests.exceptions.Timeout:
        return []
    except requests.exceptions.RequestException as e:
        print(f"[iNaturalist] API error: {e}")
        return []


# ── PlantNet client ──────────────────────────────────────────

PLANTNET_URL = "https://my-api.plantnet.org/v2/identify/all"


def identify_plantnet(image_bytes, api_key, top_n=5):
    """
    Identify plant species from image using PlantNet API.

    Free tier: 500 identifications/day.
    Requires API key and attribution ("powered by Pl@ntNet" logo).
    Response time: 1-3 seconds.

    Args:
        image_bytes: Raw image bytes (JPEG/PNG).
        api_key: PlantNet API key.
        top_n: Max results to return (default 5).

    Returns:
        List of dicts: [{scientific_name, common_names, score, gbif_id}, ...]
        OR empty list on error.
    """
    try:
        resp = requests.post(
            f"{PLANTNET_URL}?api-key={api_key}",
            files={"images": ("weed.jpg", BytesIO(image_bytes), "image/jpeg")},
            data={"organs": ["auto"]},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        results = []
        for r in data.get("results", [])[:top_n]:
            results.append({
                "scientific_name": r["species"]["scientificNameWithoutAuthor"],
                "common_names": r["species"].get("commonNames", []),
                "score": round(r["score"], 4),
                "gbif_id": r.get("gbif", {}).get("id"),
            })

        return results

    except requests.exceptions.Timeout:
        return []
    except requests.exceptions.RequestException as e:
        print(f"[PlantNet] API error: {e}")
        return []


# ── unified interface ────────────────────────────────────────

def identify_plant(image_bytes, service="inaturalist", api_key=None, top_n=5):
    """
    Identify plant species from image. Unified interface.

    Args:
        image_bytes: Raw image bytes (JPEG/PNG).
        service: "inaturalist" (default, free) or "plantnet" (needs api_key).
        api_key: Required for PlantNet. Ignored for iNaturalist.
        top_n: Max results to return.

    Returns:
        List of dicts with keys: scientific_name, common_name(s), score.
        The 'common_name' key is always a single string (first common name).
        The 'common_names' key (PlantNet only) is the full list.
    """
    if service == "plantnet":
        if not api_key:
            raise ValueError("PlantNet requires an API key. "
                             "Get one at https://my.plantnet.org/")
        results = identify_plantnet(image_bytes, api_key, top_n=top_n)
        # Normalize: add singular common_name for consistency
        for r in results:
            if r.get("common_names"):
                r["common_name"] = r["common_names"][0]
            else:
                r["common_name"] = ""
        return results

    # Default: iNaturalist
    return identify_inaturalist(image_bytes, top_n=top_n)


# ── helper: image to base64 (for PWA / JSON transport) ──────

def image_to_base64(image_bytes):
    """Convert image bytes to base64 data URI for JSON transport."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


# ── quick test ────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python plant_id.py <image_path> [plantnet_api_key]")
        print("  Tests identification against iNaturalist (default) or PlantNet.")
        sys.exit(1)

    path = sys.argv[1]
    with open(path, "rb") as f:
        img = f.read()

    api_key = sys.argv[2] if len(sys.argv) > 2 else None

    if api_key:
        print("Using PlantNet...")
        results = identify_plant(img, service="plantnet", api_key=api_key)
    else:
        print("Using iNaturalist...")
        results = identify_plant(img)

    for r in results:
        cn = r.get("common_name", r.get("common_names", [""])[0] if isinstance(r.get("common_names"), list) else "")
        print(f"  {r['scientific_name']} ({cn}): {r['score']:.1%}")
