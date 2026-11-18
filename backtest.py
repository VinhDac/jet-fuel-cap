"""Both sides of a jet fuel policy, on public data. Writes results.json.

Run: python backtest.py
"""
import datetime as dt
import json
import math
import os

import numpy as np

from desk import VOLUME_M, ledger
from model import Market, Policy, asian_call, month_index, rolled_shape

HERE = os.path.dirname(os.path.abspath(__file__))
YEARS = range(2008, 2027)
OTM = 0.10
LIMIT = 1.00
GALLONS_M = 12 * VOLUME_M  # million gallons a year
PRE_WAR = dt.date(2026, 2, 27)
LAYERS = [(0.0, 0.5), (0.5, 1.0), (1.0, 2.0), (2.0, None)]
SPIKES = [
    ("Gulf War", dt.date(1990, 8, 1), dt.date(1991, 2, 28)),
    ("Hurricanes Katrina and Rita", dt.date(2005, 8, 25), dt.date(2005, 11, 30)),
    ("2008 oil spike", dt.date(2008, 1, 1), dt.date(2008, 9, 30)),
    ("Ukraine", dt.date(2022, 2, 24), dt.date(2022, 12, 31)),
]


def r(x, n=4):
    return None if x is None else round(float(x), n)


def m(x):
    return r(x * VOLUME_M, 2)


def dated(pair):
    return {"m": m(pair[0]), "on": pair[1].isoformat()}


def side(led):
    return {
        "hedge_m": m(led["hedge"]),
        "net_m": m(led["net"]),
        "low_cash": dated(led["low_cash"]),
        "peak_im": dated(led["peak_im"]),
        "worst_hedge": dated(led["low_vm"]),
    }


def one_year(mkt, year, limit):
    p = Policy(mkt, year, otm=OTM, limit=limit)
    bare = ledger(p, None)
    path = p.swap_margin()
    back = min(path, key=lambda x: x[2])
    held = min(path, key=lambda x: x[1])
    return {
        "year": year,
        "t0": p.t0.isoformat(),
        "S": r(p.S),
        "K": r(p.K),
        "vol": r(p.base_vol),
        "premium_m": m(bare["premium"]),
        "claims_m": m(bare["claims"]),
        "open_m": m(bare["open_liability"]),
        "unhedged_net_m": m(bare["net"]),
        "ho": side(ledger(p, "ho")),
        "brent": side(ledger(p, "brent")),
        "swap_call_back": dated((max(-back[2], 0), back[0])),
        "swap_call_held": dated((max(-held[1], 0), held[0])),
    }


def layers(mkt):
    """Premium and claims, layer by layer above the attachment point."""
    out = [{"from": a, "to": b, "premium_m": 0.0, "claims_m": 0.0, "claims_excl_2026_m": 0.0} for a, b in LAYERS]
    for year in YEARS:
        p = Policy(mkt, year, otm=OTM)
        avgs = p.averages()
        for i in range(12):
            t = [(x - p.t0).days / 365.0 for x in p.fix_days[i]]
            s = p.sigma(p.t0, i)
            call = lambda k: asian_call(p.F[i], k, s, t, p.df[i])[0]
            settled = p.last_fixing(i) is not None
            for row in out:
                a, b = row["from"], row["to"]
                v = call(p.K + a) - (call(p.K + b) if b is not None else 0.0)
                row["premium_m"] += v * VOLUME_M
                if settled:
                    over = max(avgs[i] - p.K - a, 0.0)
                    pay = min(over, b - a) if b is not None else over
                    row["claims_m"] += pay * VOLUME_M
                    if year != 2026:
                        row["claims_excl_2026_m"] += pay * VOLUME_M
    for row in out:
        for k in ("premium_m", "claims_m", "claims_excl_2026_m"):
            row[k] = r(row[k], 2)
    return out


def forward_errors(mkt):
    """How wide forward errors really were, against the width the pricing model gave them."""
    res = {}
    origins = [d for d in mkt.days if d.year >= 2007 and (d + dt.timedelta(days=4)).month != d.month]
    for d in origins:
        vol = mkt.market_vol(d)
        for k in range(1, 13):
            idx = month_index(d.year, d.month) + k
            y, mo = idx // 12, idx % 12 + 1
            fx = mkt.fixings.get((y, mo))
            if not fx or len(fx) < 15 or (y, mo) > (2026, 10):
                continue
            T = (dt.date(y, mo, 15) - d).days / 365
            s = vol * rolled_shape(k) * math.sqrt(T)
            res.setdefault(k, []).append((math.log(np.mean([p for _, p in fx]) / mkt.jet_forward(d, y, mo)) / s, y))
    out = {}
    for k, v in res.items():
        z = np.array([a for a, _ in v])
        calm = np.array([a for a, y in v if y not in (2020, 2022, 2026)])
        out[k] = {"all": r(z.std(), 3), "without_2020_2022_2026": r(calm.std(), 3), "n": len(z)}
    return out


def spikes(mkt):
    days = sorted(mkt.jet)
    out = []
    for name, a, b in SPIKES:
        window = [d for d in days if a <= d <= b]
        base = float(np.mean([mkt.jet[d] for d in days if a - dt.timedelta(days=45) <= d < a]))
        peak = max(window, key=lambda d: mkt.jet[d])
        half = base + (mkt.jet[peak] - base) / 2
        hit = next(d for d in days if d > peak and mkt.jet[d] <= half)
        out.append({"name": name, "base": r(base, 3), "peak": r(mkt.jet[peak], 3), "peak_on": peak.isoformat(), "days_to_half": (hit - peak).days})
    return out


def two_prices(mkt, seed=11):
    """What it costs to replicate a cap, and what caps like it have cost to pay.

    Per dollar of swap rate, so that years with different price levels can be put together.
    The second figure has a range because it rests on nineteen years: years drawn with repeats.
    """
    rng = np.random.default_rng(seed)
    out = []
    for otm in (0.0, 0.10, 0.20, 0.30):
        rep, burn, burn_to_2025 = [], [], []
        for year in YEARS:
            p = Policy(mkt, year, otm=otm)
            avgs = [(i, a) for i, a in enumerate(p.averages()) if a is not None and p.last_fixing(i) is not None]
            rep.append(p.premium / p.S)
            b = float(np.mean([max(a - p.K, 0.0) for _, a in avgs])) / p.S
            burn.append(b)
            if year <= 2025:
                burn_to_2025.append(b)
        rep, burn = np.array(rep), np.array(burn)
        draws = rng.integers(0, len(burn), (20000, len(burn)))
        means = burn[draws].mean(axis=1)
        out.append(
            {
                "otm": otm,
                "replication": r(rep.mean()),
                "burn": r(burn.mean()),
                "burn_to_2025": r(np.mean(burn_to_2025)),
                "burn_low": r(np.quantile(means, 0.05)),
                "burn_high": r(np.quantile(means, 0.95)),
                "ratio": r(burn.mean() / rep.mean(), 2),
                "ratio_to_2025": r(np.mean(burn_to_2025) / rep[:-1].mean(), 2),
            }
        )
    return out


def hindsight(mkt):
    """A cap struck at the swap rate: each month, the cheaper of the swap and no hedge, for a fee."""
    rows = []
    for year in YEARS:
        p = Policy(mkt, year, otm=0.0)
        fee = float((p.caplets / p.df).mean())
        pairs = [a for i, a in enumerate(p.averages()) if a is not None and p.last_fixing(i) is not None]
        none = float(np.mean(pairs))
        cap = float(np.mean([min(a, p.S) for a in pairs])) + fee
        rows.append({"year": year, "S": r(p.S), "fee": r(fee), "none": r(none), "swap": r(p.S), "cap": r(cap), "regret_none": r(none - min(none, p.S)), "regret_swap": r(p.S - min(none, p.S)), "regret_cap": r(cap - min(none, p.S))})
    return rows


def fit_quality(mkt):
    """How much of jet's daily move each hedge explains, by period."""
    days = sorted(mkt.jet)
    pairs = [(q, mkt.jet[q] - mkt.jet[p]) for p, q in zip(days, days[1:]) if (q - p).days <= 5]
    out = {}
    for label, a, b in (("2008-2019", 2008, 2019), ("2020-2025", 2020, 2025), ("2026", 2026, 2026)):
        row = {}
        for name, ch, scale in (("ho", mkt.dh, 1.0), ("brent", mkt.db, 42.0)):
            xy = np.array([(v, ch[q] / scale) for q, v in pairs if a <= q.year <= b and q in ch])
            row[name] = r(np.corrcoef(xy[:, 0], xy[:, 1])[0, 1] ** 2, 3)
        out[label] = row
    return out


def front_side(mkt, errors):
    t0 = mkt.days[-1]
    spot = mkt.jet[t0]
    base = Policy(mkt, 2027, t0=t0, strike=spot)
    fwd_pre = np.array([mkt.jet_forward(PRE_WAR, 2027, mo) for mo in range(1, 13)])
    swap_pre = float((base.df * fwd_pre).sum() / base.df.sum())
    wide = float(np.mean([errors[k]["all"] for k in range(6, 13)]))

    def fee(strike, limit=None, scale=1.0):
        q = Policy(mkt, 2027, t0=t0, strike=strike, limit=limit, vol_scale=scale)
        return float((q.caplets / q.df).mean()), q.premium

    prices = {}
    for label, scale in (("low", 0.8), ("market", 1.0), ("high", 1.25), ("history", wide)):
        hind, cap, layer = fee(base.S, None, scale), fee(spot, None, scale), fee(spot, LIMIT, scale)
        prices[label] = {
            "vol_scale": r(scale, 3),
            "hindsight": r(hind[0]),
            "hindsight_m": r(hind[1] * GALLONS_M, 1),
            "cap": r(cap[0]),
            "cap_m": r(cap[1] * GALLONS_M, 1),
            "layer": r(layer[0]),
            "layer_m": r(layer[1] * GALLONS_M, 1),
        }
    h, c, l = fee(base.S)[0], fee(spot)[0], fee(spot, LIMIT)[0]
    scen = []
    for name, a in (("back to the pre-war curve", swap_pre), ("the market is right", base.S), ("stays at today's price", spot), ("gets worse", 5.50)):
        pay = max(a - spot, 0.0)
        row = {"none": a, "swap": base.S, "hindsight": min(a, base.S) + h, "cap": a - pay + c, "layer": a - min(pay, LIMIT) + l}
        best = min(a, base.S)
        scen.append({"name": name, "jet": r(a, 6), **{k: r(v, 6) for k, v in row.items()}, "regret": {k: r(v - best, 6) for k, v in row.items()}})
    worst = {k: r(max(s["regret"][k] for s in scen)) for k in ("none", "swap", "hindsight", "cap", "layer")}
    return {
        "worst_regret": worst,
        "t0": t0.isoformat(),
        "jet": spot,
        "jet_pre_war": mkt.jet[PRE_WAR],
        "differential": r(mkt.differential(t0)),
        "forwards": [r(x) for x in base.F],
        "swap": r(base.S),
        "swap_pre_war": r(swap_pre),
        "fuel_bill_m": r(base.S * GALLONS_M, 1),
        "call_if_peace_m": r(float((base.df * (base.S - fwd_pre)).sum()) * VOLUME_M, 1),
        "front_vol": r(mkt.front_vol(t0)),
        "market_vol": r(mkt.market_vol(t0)),
        "ovx": mkt.ovx[max(d for d in mkt.ovx if d <= t0)],
        "forward_below_spot": [r(1 - x / spot) for x in base.F],
        "prices": prices,
        "scenarios": scen,
    }


def charts(mkt):
    """What the page draws, and what it needs to reprice the 2027 cover in the browser."""
    t0 = mkt.days[-1]
    base = Policy(mkt, 2027, t0=t0, strike=mkt.jet[t0])
    out = {
        "climb": [[d.isoformat(), mkt.jet[d]] for d in sorted(mkt.jet) if dt.date(2026, 1, 1) <= d <= t0],
        "cover": {
            "t0": t0.isoformat(),
            "spot": mkt.jet[t0],
            "S": r(base.S, 6),
            "F": [r(x, 6) for x in base.F],
            "df": [r(x, 7) for x in base.df],
            "sigma": [r(base.sigma(t0, i), 6) for i in range(12)],
        },
        "runways": {},
    }
    for year in (2020, 2022, 2026):
        row = {}
        swap = {d: max(-b_, 0.0) for d, _, b_ in Policy(mkt, year, otm=OTM).swap_margin()}
        row["swap"] = [[d.isoformat(), r(v * VOLUME_M, 1)] for d, v in sorted(swap.items())]
        for lim_name, limit in (("none", None), ("one", LIMIT)):
            p = Policy(mkt, year, otm=OTM, limit=limit)
            for inst in ("ho", "brent"):
                led = ledger(p, inst, keep_path=True)
                row[f"{inst}_{lim_name}"] = {
                    "days": [x[0].isoformat() for x in led["path"]],
                    "before_im": [r(x[1] * VOLUME_M, 1) for x in led["path"]],
                    "im": [r(x[2] * VOLUME_M, 1) for x in led["path"]],
                }
        out["runways"][year] = row
    return out


def main():
    mkt = Market()
    plain = [one_year(mkt, y, None) for y in YEARS]
    limited = [one_year(mkt, y, LIMIT) for y in YEARS]
    errors = forward_errors(mkt)
    out = {
        "as_of": mkt.days[-1].isoformat(),
        "volume_m_gal_a_month": VOLUME_M,
        "otm": OTM,
        "limit": LIMIT,
        "no_limit": plain,
        "with_limit": limited,
        "layers": layers(mkt),
        "forward_errors": errors,
        "spikes": spikes(mkt),
        "fit": fit_quality(mkt),
        "front": front_side(mkt, errors),
        "two_prices": two_prices(mkt),
        "hindsight": hindsight(mkt),
        "charts": charts(mkt),
    }
    with open(os.path.join(HERE, "results.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=0, separators=(",", ":"))
    return out


if __name__ == "__main__":
    res = main()
    print(json.dumps({k: res[k] for k in ("spikes", "fit")}, indent=1))
    print({k: v for k, v in res["forward_errors"].items() if k in (1, 3, 6, 9, 12)})
