"""Where the fixed numbers in model.py come from. Run: python calibrate.py"""
import datetime as dt
import math

import numpy as np

from model import Market, month_index, rolled_shape, shape


def eia_ratios(mkt):
    days = [d for d in sorted(mkt.eia) if d.year >= 2008]
    rets = [[] for _ in range(4)]
    for p, q in zip(days, days[1:]):
        if (q - p).days > 5:
            continue
        roll = (p.year, p.month) != (q.year, q.month)
        for k in range(4):
            if not (roll and k == 3):
                rets[k].append(math.log(mkt.eia[q][k] / mkt.eia[p][k + 1 if roll else k]))
    v = [np.std(r, ddof=1) for r in rets]
    return {k + 1: v[k] / v[0] for k in range(4)}


def listed_vols(mkt, lo, hi):
    by = {}
    for idx, c in mkt.listed.items():
        days = sorted(c)
        for p, q in zip(days, days[1:]):
            if (q - p).days <= 5 and lo <= q <= hi:
                k = idx - month_index(q.year, q.month)
                if k >= 1:
                    by.setdefault(k, []).append(math.log(c[q] / c[p]))
    return {k: float(np.std(v, ddof=1)) for k, v in by.items() if len(v) > 60}


def main():
    mkt = Market()
    near = eia_ratios(mkt)
    war = listed_vols(mkt, dt.date(2026, 3, 1), dt.date(2026, 11, 18))
    target = dict(near)
    for k, v in war.items():
        if 5 <= k <= 24:
            target[k] = near[4] * v / war[4]
    best = None
    for a in np.arange(0.40, 0.81, 0.01):
        for b in np.arange(0.03, 0.31, 0.01):
            err = sum((a + (1 - a) * math.exp(-b * (k - 1)) - t) ** 2 for k, t in target.items())
            if best is None or err < best[0]:
                best = (err, a, b)
    print("target ratios to the front contract:", {k: round(v, 3) for k, v in sorted(target.items())})
    print("best fit: floor %.2f, decay %.2f" % (best[1], best[2]))
    print("in use:", {k: round(shape(k), 3) for k in (1, 2, 3, 4, 6, 9, 12, 18, 24)})

    # options against what followed: OVX and crude's realised volatility over the next 30 days
    days = sorted(d for d in mkt.ovx if d in mkt.wti and mkt.wti[d] > 5)
    r = np.diff(np.log([mkt.wti[d] for d in days]))
    pairs = []
    for i in range(0, len(r) - 30):
        d = days[i]
        if not dt.date(2020, 2, 15) <= d <= dt.date(2020, 7, 31):
            pairs.append((mkt.ovx[d], r[i:i + 30].std(ddof=1) * math.sqrt(252) * 100))
    a = np.array(pairs)
    print("OVX mean %.1f, crude's realised volatility in the next 30 days %.1f, ratio %.2f (spring 2020 left out)" % (a[:, 0].mean(), a[:, 1].mean(), a[:, 0].mean() / a[:, 1].mean()))

    # forward errors: did the model's spread match what happened?
    print("\nmonthly average against the forward k months earlier, 2008-2026: standard deviation of ln(average/forward) / model")
    res = {}
    for d in [x for x in mkt.days if x.year >= 2007 and (x + dt.timedelta(days=4)).month != x.month]:
        vol = mkt.market_vol(d)
        for k in range(1, 13):
            idx = month_index(d.year, d.month) + k
            y, m = idx // 12, idx % 12 + 1
            fx = mkt.fixings.get((y, m))
            if not fx or len(fx) < 15 or (y, m) > (2026, 10):
                continue
            F = mkt.jet_forward(d, y, m)
            if F <= 0:
                continue
            T = (dt.date(y, m, 15) - d).days / 365
            s = vol * rolled_shape(k) * math.sqrt(T)
            res.setdefault(k, []).append((math.log(np.mean([p for _, p in fx]) / F), s, y))
    print("k  all years        without 2020 and 2026")
    for k in (1, 2, 3, 6, 9, 12):
        z = np.array([e / s for e, s, _ in res[k]])
        w = np.array([e / s for e, s, y in res[k] if y not in (2020, 2026)])
        print(k, "%.2f  (mean %+.2f)   %.2f  (mean %+.2f)  n=%d" % (z.std(), z.mean(), w.std(), w.mean(), len(z)))


if __name__ == "__main__":
    main()
