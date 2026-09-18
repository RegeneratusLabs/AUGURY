import json,re,html,subprocess,os,sys
os.makedirs('_tools/cache/pages',exist_ok=True)
UA="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
d=json.load(open('soil_indicators_batch1.json'))
urls=set()
for s in d['species']:
    for x in s['sources']: urls.add(x['url'])
    for n in s['nutrients']: urls.add(n['url'])
def fetch(u):
    key=re.sub(r'\W+','_',u)[-120:]
    fp=f'_tools/cache/pages/{key}'
    if os.path.exists(fp) and os.path.getsize(fp)>500:
        return open(fp,encoding='utf-8',errors='replace').read()
    if u.endswith('.pdf'):
        raw=subprocess.run(["curl","-sS","-L","--max-time","120","-A",UA,u],capture_output=True).stdout
        open(fp+'.pdf','wb').write(raw)
        subprocess.run(["pdftotext","-layout",fp+'.pdf',fp],capture_output=True)
    else:
        raw=subprocess.run(["curl","-sS","-L","--max-time","60","-A",UA,u],capture_output=True).stdout
        t=raw.decode('utf-8','replace')
        t=re.sub(r'(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>',' ',t)
        t=re.sub(r'(?is)<br\s*/?>|</p>|</div>|</li>|</h[1-6]>|</tr>|</td>',' ',t)
        t=re.sub(r'(?s)<[^>]+>',' ',t); t=html.unescape(t)
        open(fp,'w',encoding='utf-8').write(t)
    return open(fp,encoding='utf-8',errors='replace').read() if os.path.exists(fp) else ''
def norm(t):
    t=t.replace('\u2019',"'").replace('\u2018',"'").replace('\u201c','"').replace('\u201d','"')
    t=t.replace('\u2013','-').replace('\u2014','-').replace('\u00a0',' ')
    t=re.sub(r'[^a-z0-9 ]',' ',t.lower()); return re.sub(r'\s+',' ',t).strip()
corpus={u:norm(fetch(u)) for u in urls}
print("fetched sources:", {u:len(c) for u,c in corpus.items() if len(c)<200} or "all ok")
# quoted phrases per species
fails=[]
for s in d['species']:
    own=[corpus[x['url']] for x in s['sources']]
    blob=' || '.join(own)
    texts=[v for v in s['indicators'].values()]+[n['detail'] for n in s['nutrients']]+[s['habitat']]
    for t in texts:
        for q in re.findall(r"'([^']{12,200})'", t):
            nq=norm(q)
            if not nq: continue
            if nq not in blob:
                fails.append((s['scientific_name'], q[:100]))
print(f"\nquoted phrases NOT found in that species' cited sources: {len(fails)}")
for sp,q in fails: print(f"  [{sp}] {q}")
