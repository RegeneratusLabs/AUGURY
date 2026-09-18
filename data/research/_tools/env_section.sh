#!/usr/bin/env bash
# Print the "What type of environment does it grow in?" section verbatim. Usage: env_section.sh <url> [label] [chars]
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
URL="$1"; LABEL="${2:-$1}"; MAX="${3:-3000}"
CACHE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/cache"
mkdir -p "$CACHE_DIR"
TMP=$(mktemp "$CACHE_DIR/tmp.XXXXXX")
code=$(curl -sS -L --max-time 45 -A "$UA" -o "$TMP" -w "%{http_code}" "$URL" 2>/dev/null)
echo "=== $LABEL | HTTP $code | $URL"
[ "$code" != "200" ] && { echo "FETCH FAILED"; exit 0; }
python3 - "$TMP" "$MAX" <<'PY'
import sys, re, html
raw=open(sys.argv[1],'rb').read(); MAX=int(sys.argv[2])
t=None
for enc in ('utf-8','cp1252','latin-1'):
    try: t=raw.decode(enc); break
    except Exception: pass
if t is None: t=raw.decode('utf-8','replace')
t=re.sub(r'(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>',' ',t)
t=re.sub(r'(?is)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>|</tr>|</td>','\n',t)
t=re.sub(r'(?s)<[^>]+>',' ',t); t=html.unescape(t)
t=re.sub(r'[ \t\xa0]+',' ',t)
lines=[l.strip() for l in t.split('\n') if l.strip()]
text='\n'.join(lines)
m=re.search(r'(?i)(what type of environment|where is it found|habitat|environment does it grow)', text)
if m:
    print(text[m.start():m.start()+MAX])
else:
    print('[no environment section found] first 1200 chars:')
    print(text[:1200])
PY
rm -f "$TMP"
