#!/usr/bin/env bash
# Tighter soil-evidence extractor. Usage: soil2.sh <url> [label]
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
URL="$1"; LABEL="${2:-$1}"
CACHE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/cache"
mkdir -p "$CACHE_DIR"
TMP=$(mktemp "$CACHE_DIR/tmp.XXXXXX")
code=$(curl -sS -L --max-time 45 -A "$UA" -o "$TMP" -w "%{http_code}" "$URL" 2>/dev/null)
echo "=== $LABEL | HTTP $code"
[ "$code" != "200" ] && { echo "FETCH FAILED"; exit 0; }
python3 - "$TMP" <<'PY'
import sys, re, html
raw=open(sys.argv[1],'rb').read()
t=None
for enc in ('utf-8','cp1252','latin-1'):
    try: t=raw.decode(enc); break
    except Exception: pass
if t is None: t=raw.decode('utf-8','replace')
t=re.sub(r'(?is)<(script|style|noscript|svg|head|nav|footer)[^>]*>.*?</\1>',' ',t)
t=re.sub(r'(?is)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>|</tr>|</td>','\n',t)
t=re.sub(r'(?s)<[^>]+>',' ',t); t=html.unescape(t)
t=re.sub(r'[ \t\xa0]+',' ',t)
lines=[l.strip() for l in t.split('\n') if l.strip()]
STRONG=r'(?i)(soil|pH|acid|alkalin|calcare|limestone|drain|waterlog|water-log|moist|drought|sand|clay|loam|fertile|fertil|nutrient|nitrogen|phosphor|potassium|calcium|salin|sodic|compact|erosion|disturb|overgraz|bare ground|bare area|desert|riparian|swamp|wetland|inundat|waterway|aquatic|waste place|roadsid|railway|habitat|environment|colonis|invad|grows? (in|on|well|best)|favou|tolerat|prefer)'
BAD=r'(?i)(herbicide|glyphosate|flupropanate|2,4-D|MCPA|permit|withholding|APVMA|spray|rate:|group [A-Z0-9]|resistance risk|biosecurity duty|land managers should)'
seen=set(); res=[]
for l in lines:
    if len(l)<30 or len(l)>700: continue
    if not re.search(STRONG,l): continue
    if re.search(BAD,l): continue
    k=re.sub(r'\W+','',l.lower())[:80]
    if k in seen: continue
    seen.add(k); res.append(l)
print('\n'.join(res)[:4500])
PY
rm -f "$TMP"
