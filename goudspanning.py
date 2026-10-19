"""Goudspanning: dagelijkse score (ONDERZOEK 200), zelfstandig zodat hij ook in een cloud-routine draait.

Vijf gemeten signalen op het slot van de laatst VOLTOOIDE goud-handelsdag (Yahoo GC=F), elk 0/1, plus een nieuwsniveau 0-2 dat
de routine na het lezen van het nieuws toevoegt. Schrijft spanning.json (+ een regel in spanning_historie.csv).

Gebruik:  python goudspanning.py --uit <map>                          alleen cijfers
          python goudspanning.py --uit <map> --analyse nieuws.json     met de nieuwsanalyse van de routine (niveau + pauze-advies)
"""
import argparse
import csv
import io
import json
import math
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "text/csv,application/json,*/*"}

# eindmodel 2010-2026 = Uitkijk.mq5 (backtest/_uitkijk_model.py), kans op >= 3% bereik de volgende dag
KOLS = ["rr0", "rr1", "rr2", "rr3", "rr4", "atr5_20", "atr20_120", "ret1", "ret5", "ret20", "ret60", "romp0", "clv0",
        "tot_bodem60", "tot_top60", "tot_bodem250", "tot_top250", "bodem_tests", "top_tests", "onrust10", "weekdag", "gvz_rang", "gvz5"]
GEM = [0.528089, 0.528293, 0.528444, 0.528619, 0.52864, 1.00549, 1.03161, 0.027491, 0.138237, 0.462482, 1.0354, 0.0127543, 0.515801,
       5.49469, 4.61593, 12.3594, 8.92363, 4.60631, 2.39783, 1.87972, 2.02043, 0.4732, 0.00623418]
SCH = [0.295858, 0.2958, 0.295783, 0.295795, 0.295822, 0.271335, 0.291013, 0.8521, 1.85695, 3.61488, 5.96844, 0.577477, 0.311703,
       3.5542, 3.59733, 7.09451, 6.96801, 4.70371, 1.42243, 2.09692, 1.39926, 0.321373, 0.116593]
COEF = [0.0863821, 0.172699, 0.078738, 0.186151, 0.194667, -0.0628665, -0.021633, -0.201617, -0.0125122, 0.0318833, -0.116721, 0.268998,
        -0.170865, -0.205996, -0.0858588, 0.279247, 0.537465, 0.198446, -0.500731, 0.30494, 0.00985629, 0.816738, 0.311083]
INTERCEPT = -4.02183

# ijking 2010-11..2026-10 (backtest/_goudspanning_ijk.py): per cijferscore de kans de volgende handelsdag
IJK = {0: dict(groot3=0.019, daal2=0.018, val5_2d=0.007), 1: dict(groot3=0.033, daal2=0.024, val5_2d=0.009),
       2: dict(groot3=0.111, daal2=0.052, val5_2d=0.022), 3: dict(groot3=0.289, daal2=0.088, val5_2d=0.026),
       4: dict(groot3=0.520, daal2=0.280, val5_2d=0.120)}


def haal(url, pogingen=4):
    for i in range(pogingen):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60).read()
        except Exception:
            if i == pogingen - 1: raise
            time.sleep(5 * (i + 1))


def yahoo(sym):
    eind = int(datetime.now(timezone.utc).timestamp())
    j = json.loads(haal(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?period1={eind - 4 * 365 * 86400}&period2={eind}&interval=1d"))
    r = j["chart"]["result"][0]; q = r["indicators"]["quote"][0]
    d = pd.DataFrame({k: q[k] for k in ("open", "high", "low", "close")}, index=pd.to_datetime(r["timestamp"], unit="s").normalize())
    return d[~d.index.duplicated(keep="last")].dropna()


def gvz():
    t = haal("https://cdn-api.cboe.com/api/global/us_indices/daily_prices/GVZ_History.csv").decode()
    d = pd.read_csv(io.StringIO(t))
    return pd.Series(d.iloc[:, 1].values, index=pd.to_datetime(d.iloc[:, 0], format="%m/%d/%Y")).sort_index()


def fred(naam):
    d = pd.read_csv(io.BytesIO(haal(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={naam}")), na_values=".")
    return pd.Series(d.iloc[:, 1].values, index=pd.to_datetime(d.iloc[:, 0])).dropna()


def rang(a, t):
    return float((a[t - 249:t] < a[t]).sum()) / 249.0


def kenmerken(g, gv, t):
    br = (g.high - g.low).values; c, o, lo_, hi_ = g.close.values, g.open.values, g.low.values, g.high.values
    a20 = br[t - 19:t + 1].mean()
    x = [rang(br, t - k) for k in range(5)]
    x += [br[t - 4:t + 1].mean() / a20, a20 / br[t - 119:t + 1].mean()]
    x += [(c[t] - c[t - n]) / a20 for n in (1, 5, 20, 60)]
    x += [(c[t] - o[t]) / br[t], (c[t] - lo_[t]) / br[t]]
    x += [(c[t] - lo_[t - 59:t + 1].min()) / a20, (hi_[t - 59:t + 1].max() - c[t]) / a20]
    lo, hi = lo_[t - 249:t + 1].min(), hi_[t - 249:t + 1].max()
    x += [(c[t] - lo) / a20, (hi - c[t]) / a20]
    x += [float((lo_[t - 249:t + 1] - lo <= 0.5 * a20).sum()), float((hi - hi_[t - 249:t + 1] <= 0.5 * a20).sum())]
    x += [float(sum(rang(br, t - k) >= 0.85 for k in range(10))), float(g.index[t].dayofweek)]
    x += [rang(gv, t), gv[t] / gv[t - 5] - 1.0]
    return dict(zip(KOLS, x))


def cijfers():
    g = yahoo("GC=F")
    nu = datetime.now(ZoneInfo("America/New_York"))
    af = nu.date() if nu.hour >= 17 else nu.date() - timedelta(days=1)    # een sessie sluit om 17:00 New York
    g = g[(g.index.date <= af) & (g.high > g.low)]
    gv = gvz().reindex(g.index).ffill(limit=3).values
    t = len(g) - 1
    x = kenmerken(g, gv, t)
    z = INTERCEPT + sum(COEF[i] * (x[k] - GEM[i]) / SCH[i] for i, k in enumerate(KOLS))
    kans = 1.0 / (1.0 + math.exp(-z))
    try:
        rr = fred("DFII10")
        rr = rr[rr.index.date <= g.index[t].date()]
        reeel5 = float(rr.iloc[-1] - rr.iloc[-6])
    except Exception:
        reeel5 = float("nan")
    spx = yahoo("^GSPC").close; vix = yahoo("^VIX").close
    spx = spx[spx.index <= g.index[t]]; vix = vix[vix.index <= g.index[t]]
    spx1, spx5, vix5 = spx.iloc[-1] / spx.iloc[-2] - 1, spx.iloc[-1] / spx.iloc[-6] - 1, vix.iloc[-1] / vix.iloc[-6] - 1
    s = {
        "model": dict(aan=kans >= 0.15, waarde=round(kans, 3), uitleg=f"kans op >= 3% bereik {kans:.0%} (aan vanaf 15%)"),
        "gvz": dict(aan=x["gvz_rang"] >= 0.80 or x["gvz5"] >= 0.05, waarde=round(float(gv[t]), 2),
                    uitleg=f"GVZ {gv[t]:.1f}, rang {x['gvz_rang']:.2f}, {x['gvz5']:+.0%} in 5 d (aan bij rang >= 0,80 of +5%)"),
        "reele_rente": dict(aan=reeel5 >= 0.20, waarde=None if math.isnan(reeel5) else round(reeel5, 2),
                            uitleg="FRED niet bereikbaar - telt niet mee" if math.isnan(reeel5) else f"10j reele rente {reeel5:+.2f} pp in 5 d (aan vanaf +0,20; enige met richting: goud omlaag)"),
        "bodem_top": dict(aan=x["tot_bodem250"] <= 1.0 or x["tot_top250"] <= 1.0, waarde=round(min(x["tot_bodem250"], x["tot_top250"]), 2),
                          uitleg=f"{x['tot_bodem250']:.1f} ATR boven de 250d-bodem, {x['tot_top250']:.1f} ATR onder de top (aan binnen 1)"),
        "aandelen": dict(aan=spx1 <= -0.03 or spx5 <= -0.05 or vix5 >= 0.30, waarde=round(float(spx5), 3),
                         uitleg=f"S&P {spx1:+.1%} vandaag / {spx5:+.1%} in 5 d, VIX {vix5:+.0%} in 5 d"),
    }
    for v in s.values(): v["aan"] = bool(v["aan"])
    score = sum(v["aan"] for v in s.values())
    return dict(handelsdag=str(g.index[t].date()), goud_slot=round(float(g.close.iloc[t]), 2), cijferscore=score,
                signalen=s, kans_volgende_dag=IJK[min(score, 4)])


KERN = ("CPI", "FOMC", "FED INTEREST", "RATE DECISION", "NONFARM", "NON-FARM", "NFP", "PCE", "PPI")


def oordeel(cs, nieuws):
    totaal = cs + (nieuws or 0)
    niveau = "ALARM" if cs >= 3 or (nieuws or 0) >= 2 or totaal >= 4 else "OPLETTEN" if totaal >= 2 else "RUSTIG"
    return totaal, niveau


def servertijd(datum, tijd_et):
    """broker = New York + 7 uur (sessie sluit 17:00 NY = 00:00 server); geeft (server, NL)"""
    ny = datetime.strptime(f"{datum} {tijd_et}", "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("America/New_York"))
    return (ny + timedelta(hours=7)).replace(tzinfo=None), ny.astimezone(ZoneInfo("Europe/Amsterdam")).replace(tzinfo=None)


def berichten(analyse, cs, voor=30, na=60):
    """pauze-advies per bericht; ondergrens: kernbericht + cijferscore >= 2 = altijd pauze"""
    uit = []
    for b in analyse.get("berichten", []):
        srv, nl = servertijd(b["datum"], b["tijd_et"])
        kern = b.get("kern") or any(k in b["naam"].upper() for k in KERN)
        pauze = bool(b.get("pauze")) or (kern and cs >= 2)
        v, n = int(b.get("voor_min") or voor), int(b.get("na_min") or na)
        reden = b.get("reden", "") if b.get("pauze") else ("ondergrens: kernbericht bij cijferscore >= 2" if pauze else "")
        uit.append(dict(naam=b["naam"], server=srv.strftime("%Y-%m-%d %H:%M"), nl=nl.strftime("%Y-%m-%d %H:%M"), kern=bool(kern),
                        verwachting=b.get("verwachting", ""), vorige=b.get("vorige", ""), verrassingsrisico=b.get("verrassingsrisico", ""),
                        context=b.get("context", ""), pauze=pauze, pauze_van=(srv - timedelta(minutes=v)).strftime("%Y-%m-%d %H:%M") if pauze else "",
                        pauze_tot=(srv + timedelta(minutes=n)).strftime("%Y-%m-%d %H:%M") if pauze else "", reden=reden))
    return uit


def tekstbestand(J, pad):
    """platte versie voor Uitkijk.mq5 (geen JSON-parser nodig): SLEUTEL=waarde, berichten en pauzes met | gescheiden"""
    r = [f"HANDELSDAG={J['handelsdag']}", f"CIJFERSCORE={J['cijferscore']}", f"NIEUWS={J['nieuws'] if J['nieuws'] is not None else '?'}",
         f"TOTAAL={J['totaal']}", f"NIVEAU={J['niveau']}", f"KANS_GROOT3={J['kans_volgende_dag']['groot3']}",
         f"AAN={','.join(k for k, v in J['signalen'].items() if v['aan']) or '-'}", f"TEKST={J['nieuws_tekst'].replace(chr(10), ' ')[:400]}"]
    for b in J["berichten"]:
        r.append(f"BERICHT={b['server'].replace('-', '.')}|{b['naam']}|{b['verrassingsrisico']}|{'PAUZE' if b['pauze'] else '-'}")
        if b["pauze"]: r.append(f"PAUZE={b['pauze_van'].replace('-', '.')}|{b['pauze_tot'].replace('-', '.')}|{b['naam']}: {b['reden']}"[:250])
    pad.write_text("\n".join(r) + "\n", encoding="utf-8")


if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--uit", default=".")
    a.add_argument("--analyse", help="nieuws.json van de routine: {nieuws: 0-2, samenvatting, berichten: [...]}")
    a = a.parse_args()
    uit = Path(a.uit); uit.mkdir(parents=True, exist_ok=True)
    J = dict(gemaakt=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), **cijfers())
    an = json.loads(Path(a.analyse).read_text(encoding="utf-8")) if a.analyse else {}
    J["nieuws"] = an.get("nieuws")
    J["nieuws_tekst"] = an.get("samenvatting", "" if a.analyse else "nieuws niet gelezen - alleen cijfers")
    J["totaal"], J["niveau"] = oordeel(J["cijferscore"], J["nieuws"])
    J["berichten"] = berichten(an, J["cijferscore"])
    (uit / "spanning.json").write_text(json.dumps(J, ensure_ascii=False, indent=1), encoding="utf-8")
    tekstbestand(J, uit / "spanning.txt")
    h = uit / "spanning_historie.csv"
    rijen = list(csv.reader(h.open(encoding="utf-8"))) if h.exists() else [["handelsdag", "cijferscore", "nieuws", "totaal", "niveau", "pauzes"] + list(J["signalen"])]
    rijen = [x for x in rijen if x[0] != J["handelsdag"]]
    rijen.append([J["handelsdag"], J["cijferscore"], J["nieuws"], J["totaal"], J["niveau"], sum(b["pauze"] for b in J["berichten"])]
                 + [int(v["aan"]) for v in J["signalen"].values()])
    with h.open("w", newline="", encoding="utf-8") as fh: csv.writer(fh).writerows(rijen)
    print(json.dumps({k: J[k] for k in ("handelsdag", "cijferscore", "nieuws", "totaal", "niveau")}, ensure_ascii=False))
    for k, v in J["signalen"].items(): print(f"  {k:<12} {'AAN' if v['aan'] else 'uit':<4} {v['uitleg']}")
    for b in J["berichten"]: print(f"  {b['nl']} NL  {b['naam']:<28} {'PAUZE ' + b['pauze_van'][11:] + '-' + b['pauze_tot'][11:] + ' server' if b['pauze'] else ''}")
