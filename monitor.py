import html
import json
import os
import re
import smtplib
import time
import urllib.parse
import urllib.request
from datetime import date
from email.mime.text import MIMEText
from pathlib import Path

BASE = Path(__file__).parent
SEEN = BASE / "seen.json"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

phrases = [
    line.strip()
    for line in (BASE / "phrases.txt").read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.strip().startswith("#")
]

INTENT = [
    "quanto custa", "quanto fica", "quantos dias", "procuro", "procurando",
    "estou buscando", "preciso de", "alguem indica", "alguma indicacao",
    "recomenda", "onde faco", "onde fazer", "vale a pena", "funciona mesmo",
    "melhor lugar", "melhor local", "depoimento", "aguardando resposta",
    "me ajudem", "dica", "diaria",
]


def strip(s):
    return html.unescape(re.sub(r"<[^>]+>", " ", s)).strip()


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def ddg(q):
    page = fetch("https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": q, "kl": "br-pt"}))
    out = []
    for b in re.split(r'class="result results_links', page)[1:10]:
        mt = re.search(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', b, re.S)
        ms = re.search(r'class="result__snippet"[^>]*>(.*?)</a>', b, re.S)
        if not mt:
            continue
        href = html.unescape(mt.group(1))
        if href.startswith("//"):
            href = "https:" + href
        if "duckduckgo.com/l/" in href:
            u = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg")
            if u:
                href = urllib.parse.unquote(u[0])
        out.append({"title": strip(mt.group(2)), "link": href,
                    "snippet": strip(ms.group(1)) if ms else ""})
    return out


def bing(q):
    page = fetch("https://www.bing.com/search?" + urllib.parse.urlencode({"q": q, "setlang": "pt-br"}))
    out = []
    for m in re.finditer(r'<li class="b_algo".*?</li>', page, re.S):
        ma = re.search(r'<h2>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', m.group(0), re.S)
        if not ma:
            continue
        mp = re.search(r'<p[^>]*>(.*?)</p>', m.group(0), re.S)
        out.append({"title": strip(ma.group(2)), "link": html.unescape(ma.group(1)),
                    "snippet": strip(mp.group(1)) if mp else ""})
        if len(out) >= 8:
            break
    return out


def norm(u):
    p = urllib.parse.urlsplit(u.lower())
    q = {k: v for k, v in urllib.parse.parse_qsl(p.query) if not k.startswith("utm_")}
    s = (p.netloc + p.path.rstrip("/")).strip()
    return s + (("?" + urllib.parse.urlencode(q)) if q else "")


def score(i):
    t = (i["title"] + " " + i["snippet"]).lower()
    return sum(t.count(w) for w in INTENT)


seen = set(norm(x) for x in json.loads(SEEN.read_text())) if SEEN.exists() else set()
rows = []
for ph in phrases:
    try:
        items = ddg(ph)
    except Exception as e:
        print(f"DDG falhou para {ph!r}: {e}")
        items = []
    if not items:
        try:
            items = bing(ph)
            print(f"Bing usado para {ph!r}: {len(items)} itens")
        except Exception as e:
            print(f"Bing falhou para {ph!r}: {e}")
    for i in items:
        if "oasisparanaense.com.br" in i["link"].lower():
            continue
        k = norm(i["link"])
        if k in seen:
            continue
        seen.add(k)
        rows.append({**i, "phrase": ph, "score": score(i)})
    time.sleep(2)

SEEN.write_text(json.dumps(sorted(seen)[-3000:]))
rows.sort(key=lambda r: -r["score"])
rows = rows[:40]

today = date.today().isoformat()
print(f"Itens novos hoje: {len(rows)}")
if rows and os.environ.get("SMTP_PASS"):
    L = [f"Boletim automatico - leads Oasis ({today})",
         f"{len(rows)} novos achados. [n] = pontos de intencao; quanto maior, mais quente. (!! = quente)\n"]
    cur = None
    for r in rows:
        if r["phrase"] != cur:
            cur = r["phrase"]
            L.append(f"\n=== Frase: {cur} ===")
        L.append((f"!! " if r["score"] >= 3 else "   ") + f"[{r['score']}] {r['title']}\n{r['link']}\n{r['snippet'][:220]}")
    msg = MIMEText("\n".join(L), "plain", "utf-8")
    msg["Subject"] = f"Boletim leads Oasis {today} - {len(rows)} novos"
    msg["From"] = f"Boletim Leads Oasis <{os.environ['SMTP_USER']}>"
    msg["To"] = os.environ["MAIL_TO"]
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=60) as s:
        s.starttls()
        s.login(os.environ["SMTP_USER"], os.environ["SMTP_PASS"])
        s.sendmail(os.environ["SMTP_USER"], [os.environ["MAIL_TO"]], msg.as_string())
    print("E-mail enviado.")
else:
    print("Sem e-mail (sem SMTP_PASS ou nada novo).")
