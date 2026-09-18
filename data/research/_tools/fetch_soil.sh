#!/usr/bin/env bash
# Fetch a URL and print only soil/habitat-relevant sentences (compact evidence extraction).
# Usage: fetch_soil.sh <url> [label]
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
URL="$1"; LABEL="${2:-$1}"
TMP=$(mktemp /tmp/fs.XXXXXX.html)
code=$(curl -sS -L --max-time 45 -A "$UA" -H "Accept-Language: en-AU,en;q=0.9" -o "$TMP" -w "%{http_code}" "$URL" 2>/dev/null)
echo "### $LABEL"
echo "### URL: $URL"
echo "### HTTP: $code  BYTES: $(stat -c%s "$TMP" 2>/dev/null)"
if [ "$code" != "200" ]; then echo "### FETCH FAILED"; rm -f "$TMP"; exit 0; fi
python3 - "$TMP" <<'PY'
import sys, re, html
raw = open(sys.argv[1], 'rb').read()
for enc in ('utf-8','cp1252','latin-1'):
    try:
        t = raw.decode(enc); break
    except Exception: continue
t = re.sub(r'(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>', ' ', t)
t = re.sub(r'(?is)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>|</tr>', '\n', t)
t = re.sub(r'(?s)<[^>]+>', ' ', t)
t = html.unescape(t)
t = re.sub(r'[ \t\xa0]+', ' ', t)
lines = [l.strip() for l in t.split('\n')]
lines = [l for l in lines if l]
text = '\n'.join(lines)
KEYS = r'(?i)\b(soil|soils|pH|acid|alkalin|calcareous|limestone|drain|waterlog|water-log|moist|drought|dry|sand|sandy|clay|loam|fertile|fertil|nutrient|nitrogen|phosphor|potassium|calcium|salinity|saline|sodic|compact|erosion|disturb|overgraz|cultivat|bare|grazing|pasture|riparian|swamp|wetland|inundat|flood|shade|waste|roadside|railway|habitat|environment|grows?|grow in|found|common)\b'
out=[]
for l in lines:
    if len(l) < 25: continue
    if re.search(KEYS, l):
        out.append(l)
seen=set(); res=[]
for l in out:
    if l in seen: continue
    seen.add(l); res.append(l)
print('\n'.join(res)[:7000])
PY
rm -f "$TMP"
