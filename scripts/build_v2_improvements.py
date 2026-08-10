#!/usr/bin/env python3
"""
V2.5 improvements:
1. Strip "AUGURY v1" header from all outputs
2. Comprehensive refusal examples covering real farmer questions
3. Add common names to more Ellenberg species
"""

import json
import csv
import re
from pathlib import Path
from collections import defaultdict

# ── Extended common name mapping ──
COMMON_NAMES = {
    "abies alba": "silver fir",
    "nassella trichotoma": "serrated tussock",
    "acer campestre": "field maple",
    "acer platanoides": "norway maple",
    "acer pseudoplatanus": "sycamore",
    "achillea millefolium": "yarrow",
    "achillea ptarmica": "sneezewort",
    "aconitum napellus": "monkshood",
    "acorus calamus": "sweet flag",
    "adonis annua": "pheasant's eye",
    "aegopodium podagraria": "ground elder",
    "agrimonia eupatoria": "agrimony",
    "agrostemma githago": "corn cockle",
    "agrostis canina": "velvet bent",
    "agrostis capillaris": "common bent",
    "agrostis stolonifera": "creeping bent",
    "ajuga reptans": "bugle",
    "alchemilla vulgaris": "lady's mantle",
    "allium oleraceum": "field garlic",
    "allium ursinum": "ramsons / wild garlic",
    "allium vineale": "crow garlic",
    "alnus glutinosa": "common alder",
    "alopecurus myosuroides": "black-grass",
    "alopecurus pratensis": "meadow foxtail",
    "amaranthus albus": "white pigweed",
    "amaranthus blitoides": "mat amaranth",
    "amaranthus deflexus": "large-fruit amaranth",
    "amaranthus graecizans": "prostrate pigweed",
    "amaranthus lividus": "livid amaranth",
    "amaranthus powellii": "Powell's amaranth",
    "amaranthus retroflexus": "redroot pigweed",
    "anagallis arvensis": "scarlet pimpernel",
    "anemone nemorosa": "wood anemone",
    "angelica sylvestris": "wild angelica",
    "anthoxanthum odoratum": "sweet vernal grass",
    "anthriscus sylvestris": "cow parsley",
    "anthyllis vulneraria": "kidney vetch",
    "arabidopsis thaliana": "thale cress",
    "arctium lappa": "greater burdock",
    "arctium minus": "lesser burdock",
    "arrhenatherum elatius": "false oat-grass",
    "artemisia absinthium": "wormwood",
    "artemisia vulgaris": "mugwort",
    "arum maculatum": "lords-and-ladies",
    "asplenium ruta-muraria": "wall rue",
    "athyrium filix-femina": "lady fern",
    "atropa bella-donna": "deadly nightshade",
    "avena fatua": "wild oat",
    "bellis perennis": "daisy",
    "berberis vulgaris": "barberry",
    "betula pendula": "silver birch",
    "betula pubescens": "downy birch",
    "bidens tripartita": "trifid bur-marigold",
    "brachypodium pinnatum": "tor-grass",
    "brachypodium sylvaticum": "false brome",
    "briza media": "quaking grass",
    "bromus erectus": "upright brome",
    "bromus hordeaceus": "soft brome",
    "bromus sterilis": "barren brome",
    "bromus tectorum": "drooping brome",
    "cakile maritima": "sea rocket",
    "calla palustris": "bog arum",
    "calluna vulgaris": "heather",
    "caltha palustris": "marsh marigold",
    "calystegia sepium": "hedge bindweed",
    "campanula rotundifolia": "harebell",
    "capsella bursa-pastoris": "shepherd's purse",
    "cardamine hirsuta": "hairy bittercress",
    "cardamine pratensis": "cuckooflower",
    "carex flacca": "glaucous sedge",
    "carex hirta": "hairy sedge",
    "carex nigra": "common sedge",
    "carex panicea": "carnation sedge",
    "carex pendula": "pendulous sedge",
    "carex sylvatica": "wood sedge",
    "centaurea cyanus": "cornflower",
    "centaurea nigra": "common knapweed",
    "centaurea scabiosa": "greater knapweed",
    "cerastium fontanum": "common mouse-ear",
    "chelidonium majus": "greater celandine",
    "chenopodium album": "fat hen",
    "chrysanthemum segetum": "corn marigold",
    "cichorium intybus": "chicory",
    "circaea lutetiana": "enchanter's nightshade",
    "cirsium arvense": "creeping thistle",
    "cirsium palustre": "marsh thistle",
    "cirsium vulgare": "spear thistle",
    "clematis vitalba": "old man's beard",
    "conium maculatum": "hemlock",
    "convallaria majalis": "lily of the valley",
    "convolvulus arvensis": "field bindweed",
    "conyza canadensis": "canadian fleabane",
    "cornus sanguinea": "dogwood",
    "corylus avellana": "hazel",
    "crataegus monogyna": "hawthorn",
    "cytisus scoparius": "broom",
    "dactylis glomerata": "cock's-foot",
    "datura stramonium": "jimsonweed",
    "daucus carota": "wild carrot",
    "deschampsia cespitosa": "tufted hair-grass",
    "digitalis purpurea": "foxglove",
    "dipsacus fullonum": "teasel",
    "drosera rotundifolia": "sundew",
    "dryopteris filix-mas": "male fern",
    "echium vulgare": "viper's bugloss",
    "elytrigia repens": "couch grass",
    "epilobium angustifolium": "fireweed",
    "epilobium hirsutum": "great willowherb",
    "equisetum arvense": "field horsetail",
    "erica tetralix": "cross-leaved heath",
    "eriophorum angustifolium": "common cottongrass",
    "euonymus europaea": "spindle",
    "eupatorium cannabinum": "hemp agrimony",
    "euphorbia helioscopia": "sun spurge",
    "euphorbia peplus": "petty spurge",
    "fagus sylvatica": "beech",
    "fallopia convolvulus": "black-bindweed",
    "festuca ovina": "sheep's fescue",
    "festuca rubra": "red fescue",
    "filipendula ulmaria": "meadowsweet",
    "fragaria vesca": "wild strawberry",
    "frangula alnus": "alder buckthorn",
    "fraxinus excelsior": "ash",
    "fumaria officinalis": "common fumitory",
    "galeopsis tetrahit": "common hemp-nettle",
    "galium aparine": "cleavers",
    "galium odoratum": "sweet woodruff",
    "galium verum": "lady's bedstraw",
    "geranium dissectum": "cut-leaved crane's-bill",
    "geranium molle": "dove's-foot crane's-bill",
    "geranium robertianum": "herb robert",
    "geum urbanum": "wood avens",
    "glechoma hederacea": "ground ivy",
    "hedera helix": "ivy",
    "heracleum sphondylium": "hogweed",
    "holcus lanatus": "yorkshire fog",
    "hypericum perforatum": "st john's wort",
    "ilex aquifolium": "holly",
    "iris pseudacorus": "yellow flag iris",
    "juncus effusus": "soft rush",
    "juncus inflexus": "hard rush",
    "lamium album": "white dead-nettle",
    "lamium purpureum": "red dead-nettle",
    "lapsana communis": "nipplewort",
    "linaria vulgaris": "common toadflax",
    "lolium perenne": "perennial ryegrass",
    "lotus corniculatus": "bird's-foot trefoil",
    "lychnis flos-cuculi": "ragged robin",
    "lycopus europaeus": "gypsywort",
    "lythrum salicaria": "purple loosestrife",
    "malva sylvestris": "common mallow",
    "matricaria discoidea": "pineapple weed",
    "medicago lupulina": "black medick",
    "myosotis arvensis": "field forget-me-not",
    "nasturtium officinale": "watercress",
    "oxalis acetosella": "wood sorrel",
    "papaver rhoeas": "common poppy",
    "persicaria maculosa": "redshank",
    "phalaris arundinacea": "reed canary grass",
    "phleum pratense": "timothy",
    "phragmites australis": "common reed",
    "plantago lanceolata": "ribwort plantain",
    "plantago major": "greater plantain",
    "plantago media": "hoary plantain",
    "poa annua": "annual meadowgrass",
    "poa pratensis": "smooth meadowgrass",
    "poa trivialis": "rough meadowgrass",
    "polygonum aviculare": "knotgrass",
    "potentilla anserina": "silverweed",
    "potentilla reptans": "creeping cinquefoil",
    "primula veris": "cowslip",
    "primula vulgaris": "primrose",
    "prunella vulgaris": "self-heal",
    "prunus spinosa": "blackthorn",
    "quercus robur": "english oak",
    "ranunculus acris": "meadow buttercup",
    "ranunculus bulbosus": "bulbous buttercup",
    "ranunculus ficaria": "lesser celandine",
    "ranunculus repens": "creeping buttercup",
    "rumex acetosa": "common sorrel",
    "rumex acetosella": "sheep's sorrel",
    "rumex crispus": "curled dock",
    "rumex obtusifolius": "broad-leaved dock",
    "salix alba": "white willow",
    "salix caprea": "goat willow",
    "salix cinerea": "grey willow",
    "sambucus nigra": "elder",
    "senecio jacobaea": "common ragwort",
    "senecio vulgaris": "groundsel",
    "sinapis arvensis": "charlock",
    "solanum dulcamara": "woody nightshade",
    "solanum nigrum": "black nightshade",
    "sonchus arvensis": "perennial sow-thistle",
    "sonchus asper": "prickly sow-thistle",
    "sonchus oleraceus": "smooth sow-thistle",
    "sorbus aucuparia": "rowan",
    "stellaria media": "common chickweed",
    "tanacetum vulgare": "tansy",
    "taraxacum officinale": "dandelion",
    "trifolium pratense": "red clover",
    "trifolium repens": "white clover",
    "tussilago farfara": "coltsfoot",
    "typha latifolia": "bulrush",
    "urtica dioica": "stinging nettle",
    "urtica urens": "small nettle",
    "veronica persica": "common field speedwell",
    "vicia cracca": "tufted vetch",
    "vicia sativa": "common vetch",
    "vicia sepium": "bush vetch",
    "viola arvensis": "field pansy",
    "viola odorata": "sweet violet",
}

# ── Refusal examples: real farmer questions they'd actually ask ──
REFUSAL_EXAMPLES = [
    # ── Management advice (most common farmer mistake) ──
    ("How do I fix soil compaction?", "management"),
    ("What can I do about waterlogging in my bottom paddock?", "management"),
    ("How do I get rid of thistles?", "management"),
    ("What spray kills capeweed?", "management"),
    ("Should I lime my paddock?", "management"),
    ("What fertiliser should I use for better pasture?", "management"),
    ("How do I improve my soil pH?", "management"),
    ("What's the best way to drain a wet field?", "management"),
    ("How do I reduce nitrogen in my soil?", "management"),
    ("What should I plant to fix salinity?", "management"),
    ("When should I spray for blackberry?", "management"),
    ("How do I control Paterson's curse?", "management"),
    ("What stocking rate should I use on this pasture?", "management"),
    ("Should I aerate my compacted paddock?", "management"),
    ("What cover crop would help this soil?", "management"),
    ("How do I improve soil organic matter?", "management"),
    ("What gypsum rate for sodic soils?", "management"),
    ("How do I manage erosion on my hillside?", "management"),

    # ── Crop / agronomy (out of scope) ──
    ("What crop should I plant in this paddock?", "agronomy"),
    ("When should I sow my winter wheat?", "agronomy"),
    ("What variety of clover is best for sheep?", "agronomy"),
    ("Is this soil good for growing vegetables?", "agronomy"),
    ("What yield can I expect from this field?", "agronomy"),
    ("Should I rotate crops here?", "agronomy"),

    # ── Non-farming small talk ──
    ("Hello!", "small talk"),
    ("Hi there", "small talk"),
    ("How are you?", "small talk"),
    ("What's your name?", "small talk"),
    ("Who made you?", "small talk"),
    ("Are you AI?", "small talk"),
    ("What can you do?", "small talk"),
    ("Tell me about yourself", "small talk"),
    ("Good morning", "small talk"),
    ("Thanks!", "small talk"),
    ("Bye", "small talk"),
    ("Help", "small talk"),

    # ── General knowledge ──
    ("What's the weather going to be?", "general"),
    ("What's the price of wheat?", "general"),
    ("Who is the prime minister?", "general"),
    ("What day is it?", "general"),
    ("What time is it?", "general"),
    ("How far is it to Melbourne?", "general"),
    ("Is it going to rain this week?", "general"),

    # ── Animal / livestock (out of scope) ──
    ("What's wrong with my sheep?", "livestock"),
    ("Why are my cattle losing weight?", "livestock"),
    ("What breed of cattle should I run?", "livestock"),
    ("Is this plant toxic to horses?", "livestock"),

    # ── Vague / confused ──
    ("My soil is bad", "vague"),
    ("The paddock looks sick", "vague"),
    ("Something is wrong with my field", "vague"),
    ("Why are my plants dying?", "vague"),
    ("Nothing grows here", "vague"),
    ("asdf", "nonsense"),
    ("12345", "nonsense"),
    ("test", "nonsense"),
]

REFUSAL_RESPONSE = (
    "I'm a soil indicator specialist — I can tell you what weeds and plants indicate "
    "about soil conditions. I don't give management advice, recommendations, or "
    "general information. Try asking me about a specific plant species you've noticed "
    "in your paddock, for example: 'What does Yorkshire fog indicate?' or "
    "'I'm seeing a lot of capeweed, what's the soil telling me?'\n"
    "Source: AUGURY"
)

SYSTEM_PROMPT = (
    "You are a soil health assistant specializing in weeds and plants as soil indicators. "
    "Given a plant species, you describe what soil conditions it indicates — including "
    "compaction, drainage, nutrient imbalances, pH, organic matter state, and microbial "
    "activity. You do NOT provide management recommendations or solutions. You respond "
    "in clear, plain language suitable for farmers."
)

DEFAULT_REGION = "[Region: Europe]"


def strip_header(text):
    """Remove 'AUGURY v1\n' prefix from responses."""
    if text.startswith("AUGURY v1\n"):
        return text[10:]
    if text.startswith("AUGURY v1"):
        return text[6:].lstrip("\n")
    return text


def generate_refusal_examples(output_path):
    """Generate refusal training examples covering real farmer questions."""
    examples = []
    for question, category in REFUSAL_EXAMPLES:
        example = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
                {"role": "assistant", "content": REFUSAL_RESPONSE},
            ]
        }
        examples.append(example)

    with open(output_path, 'w', encoding='utf-8') as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + '\n')

    return len(examples)


def strip_and_add_names(input_path, output_path):
    """Strip AUGURY v1 header and add common names to responses."""
    with open(input_path, encoding='utf-8') as f:
        examples = [json.loads(line) for line in f if line.strip()]

    stripped = 0
    named = 0

    for ex in examples:
        resp = ex['messages'][2]['content']

        # Strip header
        new_resp = strip_header(resp)
        if new_resp != resp:
            stripped += 1

        # Add common name if we know it
        q = ex['messages'][1]['content']
        sci_name = None
        for tmpl_prefix in ['[Region: Europe] What does ', '[Region: UK] What does ', '[Region: Australia] What does ']:
            if q.startswith(tmpl_prefix):
                sci_name = q[len(tmpl_prefix):].split(' indicate')[0].strip()
                break
        if not sci_name:
            m = re.search(r'does (.+?) indicate', q)
            if m:
                sci_name = m.group(1).strip()

        if sci_name:
            sci_lower = sci_name.lower().strip()
            common = COMMON_NAMES.get(sci_lower)
            if common and not sci_name.startswith(common):
                # Only add name line if not already present and not a CAWR-style response
                if "General indicators" not in new_resp and "Species:" not in new_resp:
                    new_resp = f"Species: {common.title()} ({sci_name})\n{new_resp}"
                    named += 1

        ex['messages'][2]['content'] = new_resp

    with open(output_path, 'w', encoding='utf-8') as f:
        for ex in examples:
            f.write(json.dumps(ex, ensure_ascii=False) + '\n')

    return stripped, named, len(examples)


def main():
    project_dir = Path(__file__).resolve().parent.parent

    # 1. Refusal examples
    refusal_path = project_dir / 'data' / 'training' / 'refusal_examples.jsonl'
    n = generate_refusal_examples(str(refusal_path))
    print(f"Refusal examples: {n}")
    categories = set(c for _, c in REFUSAL_EXAMPLES)
    print(f"  Categories: {len(categories)} ({', '.join(sorted(categories))})")

    # 2. Strip headers + add names to Ellenberg
    src = project_dir / 'data' / 'training' / 'ellenberg_indicators_v2.jsonl'
    if not src.exists():
        src = project_dir / 'data' / 'training' / 'ellenberg_indicators.jsonl'

    out = project_dir / 'data' / 'training' / 'ellenberg_indicators_v2.jsonl'
    stripped, named, total = strip_and_add_names(str(src), str(out))
    print(f"\nEllenberg: {stripped}/{total} headers stripped, {named}/{total} common names added → {out}")

    # 3. Strip headers from Maughan & Amos
    for label, fname in [
        ("Maughan 2022", "maughan_amos_2022.jsonl"),
        ("Maughan 2024", "maughan_amos_2024.jsonl"),
    ]:
        path = project_dir / 'data' / 'training' / fname
        if path.exists():
            with open(path) as f:
                data = [json.loads(l) for l in f if l.strip()]
            for ex in data:
                ex['messages'][2]['content'] = strip_header(ex['messages'][2]['content'])
            with open(path, 'w') as f:
                for ex in data:
                    f.write(json.dumps(ex, ensure_ascii=False) + '\n')
            print(f"{label}: headers stripped from {len(data)} examples")

    print("\nNext: run merge_datasets.py")


if __name__ == '__main__':
    main()
