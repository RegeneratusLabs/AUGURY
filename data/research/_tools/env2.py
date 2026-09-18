import sys, re, html, subprocess
url=sys.argv[1]; phrase=sys.argv[2]; n=int(sys.argv[3]) if len(sys.argv)>3 else 2000
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
raw=subprocess.run(["curl","-sS","-L","--max-time","45","-A",UA,url],capture_output=True).stdout
t=None
for enc in ('utf-8','cp1252','latin-1'):
    try: t=raw.decode(enc); break
    except Exception: pass
t=t or raw.decode('utf-8','replace')
t=re.sub(r'(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>',' ',t)
t=re.sub(r'(?is)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>|</tr>|</td>','\n',t)
t=re.sub(r'(?s)<[^>]+>',' ',t); t=html.unescape(t); t=re.sub(r'[ \t\xa0]+',' ',t)
lines=[l.strip() for l in t.split('\n') if l.strip()]; text='\n'.join(lines)
idx=text.lower().find(phrase.lower())
print(f"=== {url}\n=== phrase='{phrase}' idx={idx}")
print(text[idx:idx+n] if idx>=0 else text[:n])
