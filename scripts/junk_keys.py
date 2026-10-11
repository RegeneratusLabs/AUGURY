#!/usr/bin/env python3
"""AUGURY — junk_keys.py

Single source of truth for keys that look like species but are not.

Why this exists
---------------
`SpeciesDB._load()` builds its species map by *parsing the training JSONL* and
extracting a scientific name from each row. The training corpus contains rows
whose "Species:" field is not a plant, so the extractor faithfully manufactures
species keys from them:

    Species: Rushes excess            -> key 'rushes excess'
    Species: Fumitory loam            -> key 'fumitory loam'
    Species: Mitchell Grass (astrebia spp)  -> key 'astrebia spp'   (misspelling)
    Species: Rhynchosinapi cheiranthos      -> key 'rhynchosinapi cheiranthos'
    Species: Tripleurosper perforatum       -> truncated mid-word

Downstream this is expensive: each junk key becomes an empty directory under
`data/vision/images/`, so a gallery audit reports dozens of phantom "species
missing images" and an acquisition run probes iNaturalist for a plant that does
not exist. That is exactly the noise this module removes.

Why a denylist and not a data fix
---------------------------------
The training JSONL is *published* (RegeneratusLabs/augury-training-data) and the
shipped LoRA was trained on it. Rewriting it would invalidate the published
artifact hashes and desynchronise the model from its own training set. So the
artefacts stay byte-identical and the junk is filtered at parse time, here.

Adding an entry
---------------
Add the exact lowercased key plus a one-line reason. Prefer fixing the upstream
generator when the source is under our control; use this list for artefacts that
are already baked into published data.
"""
from __future__ import annotations

# UK soil-association pseudo-species: "Dandelion clay" means "dandelion indicates
# clay", i.e. a soil association, not a plant. augury_funnel.CLAY_PSEUDO_SPECIES
# deliberately still recognises these so a user can paste one and get an honest
# answer; they must not exist as *species* keys.
PSEUDO_SPECIES = {
    "chicory clay", "dandelion clay", "goosegrass clay", "plantains clay",
    "fumitory loam", "rushes excess", "timothy heavy",
}

# Names truncated mid-word by an upstream extraction bug. Each has a correctly
# spelled sibling elsewhere in the DB:
#   'tripleurosper perforatum'   -> tripleurospermum maritimum (has 50 images)
#   'rhynchosinapi cheiranthos'  -> Rhynchosinapia cheiranthos
TRUNCATED_KEYS = {
    "tripleurosper perforatum", "rhynchosinapi cheiranthos",
}

# Misspellings of real genera that already have a correct entry:
#   'astrebia spp'        -> Astrebla spp (Mitchell grass)
#   'fallopia convovulvus' -> fallopia convolvulus (black-bindweed; the
#                            misspelling carries 1 UK row against the correct
#                            key's 3 UK + 3 Europe, so it is a lossy duplicate)
MISSPELLED_KEYS = {
    "astrebia spp", "fallopia convovulvus",
}

# Vernacular names cut off at the hyphen by the mining layer's name extractor,
# each of which has a correctly named sibling in the database carrying the real
# indicator rows. They surfaced as first-class "species" in a name picker
# because the fragment — not the plant — had been stored as the key.
#   'field forget'   -> myosotis arvensis    (Field forget-me-not)
#   'italian rye'    -> lolium multiflorum   (Italian ryegrass)
#   'perennial sow'  -> sonchus arvensis     (Perennial sowthistle)
#   'henbit dead'    -> lamium amplexicaule  (Henbit dead-nettle)
#   'red dead'       -> lamium purpureum     (Red dead-nettle)
TRUNCATED_VERNACULAR_KEYS = {
    "field forget", "italian rye", "perennial sow", "henbit dead", "red dead",
}

# Catch-all buckets that are not taxa.
MISC_JUNK = {
    "unknown",
}

# Every non-species key, lowercased.
JUNK_KEYS = frozenset(
    PSEUDO_SPECIES | TRUNCATED_KEYS | MISSPELLED_KEYS | TRUNCATED_VERNACULAR_KEYS | MISC_JUNK
)


def is_junk(key: str) -> bool:
    """True when `key` is a known non-species artefact."""
    return (key or "").strip().lower() in JUNK_KEYS


if __name__ == "__main__":
    for name, group in (("pseudo-species", PSEUDO_SPECIES), ("truncated", TRUNCATED_KEYS),
                        ("misspelled", MISSPELLED_KEYS),
                        ("truncated vernacular", TRUNCATED_VERNACULAR_KEYS), ("misc", MISC_JUNK)):
        print(f"{name} ({len(group)}):")
        for k in sorted(group):
            print(f"   {k}")
    print(f"\ntotal junk keys: {len(JUNK_KEYS)}")
