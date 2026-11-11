import requests, io, zipfile, os, sys, numpy as np, concurrent.futures as cf
D=os.environ.get("RESEARCH_DATA") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"); os.makedirs(D, exist_ok=True); s=requests.Session()
t=s.get("https://api.toobit.com/quote/v1/contract/ticker/24hr",timeout=30).json()
t=[x for x in t if x["s"].endswith("-SWAP-USDT")]
t.sort(key=lambda x:-float(x["qv"]))
top=[x["s"].split("-")[0] for x in t[:70]]
vol=[x for x in t if float(x["qv"])>=1e6 and float(x["c"])>0]
vol.sort(key=lambda x:-(float(x["h"])-float(x["l"]))/float(x["c"]))
vola=[x["s"].split("-")[0] for x in vol[:40]]
print("top",top); print("vola",vola)
months=[f"{y}-{m:02d}" for y in (2024,2025,2026) for m in range(1,13)]
months=[m for m in months if "2024-07"<=m<="2026-10"]
def get(sym,m):
    u=f"https://data.binance.vision/data/futures/um/monthly/klines/{sym}USDT/5m/{sym}USDT-5m-{m}.zip"
    for _ in range(3):
        try:
            r=s.get(u,timeout=60)
            if r.status_code==404: return None
            if r.status_code==200:
                z=zipfile.ZipFile(io.BytesIO(r.content)); txt=z.read(z.namelist()[0]).decode()
                rows=[l.split(",")[:6] for l in txt.strip().split("\n") if l[0].isdigit()]
                return np.array(rows,dtype=float)
        except Exception as e: pass
    return None
def coin(sym):
    f=f"{D}/{sym}.npy"
    if os.path.exists(f): return sym,-1
    parts=[a for a in cf.ThreadPoolExecutor(6).map(lambda m:get(sym,m),months) if a is not None and len(a)]
    if not parts: return sym,0
    a=np.concatenate(parts); a[:,0]//=1000 if a[0,0]<1e14 else 1000000
    a=a[np.argsort(a[:,0])]; np.save(f,a); return sym,len(a)
names=list(dict.fromkeys(top+vola))
with cf.ThreadPoolExecutor(4) as ex:
    for sym,n in ex.map(coin,names): print(sym,n,flush=True)
import json; json.dump({"top":top,"vola":vola},open(f"{D}/lists.json","w"))
