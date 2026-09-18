import json,re,html,glob,os
d=json.load(open('soil_indicators_batch1.json'))
def load(u):
    key=re.sub(r'\W+','_',u)[-120:]
    for fp in (f'_tools/cache/pages/{key}.clean', f'_tools/cache/pages/{key}', f'_tools/cache/pages/{key}.txt'):
        if os.path.exists(fp) and not fp.endswith('.pdf'):
            t=open(fp,encoding='utf-8',errors='replace').read()
            if len(t)>500: return t
    return ''
def tight(t):
    t=t.replace('\u2019',"'").replace('\u2018',"'").replace('\u00a0',' ')
    return re.sub(r'[^a-z0-9]','',t.lower().replace('[sic]',''))
urls=sorted({x['url'] for s in d['species'] for x in s['sources']} | {n['url'] for s in d['species'] for n in s['nutrients']})
corp={u:tight(load(u)) for u in urls}
missing=[u for u,c in corp.items() if len(c)<200]
print("empty/short corpus:", missing or "none")
# token-aware quote extraction: opening ' preceded by start/space/( and closing ' followed by space/punct/end
QS=re.compile(r"(?:(?<=^)|(?<=[\s(]))'([^']{14,240})'(?=[\s.,;)\]]|$)")
fails=[]
for s in d['species']:
    blob=' '.join(corp[x['url']] for x in s['sources'])
    texts=list(s['indicators'].values())+[n['detail'] for n in s['nutrients']]+[s.get('habitat','')]
    for t in texts:
        for q in QS.findall(t):
            tq=tight(q)
            if len(tq)<14: continue
            if tq not in blob:
                fails.append((s['scientific_name'],q[:130]))
print(f"\nREAL quote mismatches: {len(fails)}")
for sp,q in fails: print(f"  [{sp}] {q}")
