"""What has to hold before any number here is used. Run: python checks.py

Each check prints what it measured. The script stops at the first one that fails.
"""
import csv
import datetime as dt
import json
import math
import os

import numpy as np

import desk
import model
from backtest import LIMIT, OTM, YEARS
from model import Market, Policy, asian_call, month_end

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = (2009, 2014, 2020, 2022, 2026)


def ok(name, passed, detail):
    print(("pass  " if passed else "FAIL  ") + name + ": " + detail, flush=True)
    if not passed:
        raise SystemExit(1)


def sources_agree(mkt):
    gaps = [abs(mkt.eia[d][0] - mkt.ho[d]) for d in mkt.eia if d in mkt.ho and d.year >= 2008]
    ok("two sources give one front contract", np.mean(gaps) < 0.002 and len(gaps) > 3000, f"EIA against the chart feed: mean gap ${np.mean(gaps):.4f} over {len(gaps)} days")


def contracts_roll_at_month_end(mkt):
    days = [d for d in sorted(mkt.eia) if d.year >= 2008]
    at = {d: i for i, d in enumerate(days)}
    turns = [p for p, q in zip(days, days[1:]) if (p.year, p.month) != (q.year, q.month)]

    def share(offset):
        hit = n = 0
        for last in turns:
            i = at[last] + offset
            if 0 <= i < len(days) - 1:
                a, b = np.array(mkt.eia[days[i]]), np.array(mkt.eia[days[i + 1]])
                hit += np.std(b[:3] - a[1:]) < np.std(b[:3] - a[:3])
                n += 1
        return hit / n

    at_turn, after = share(0), share(1)
    ok("the curve rolls at the turn of the month", at_turn > 0.75 and after < 0.4, f"{at_turn:.0%} of month turns look rolled, {after:.0%} of the next days")


def nothing_is_known_early(mkt):
    for y in YEARS:
        full = Policy(mkt, y, otm=OTM)
        cut = Policy(Market(until=full.t0), y, otm=OTM)
        if not (full.S == cut.S and full.base_vol == cut.base_vol and np.array_equal(full.caplets, cut.caplets)):
            ok("no look-ahead", False, f"{y} changes when the future is removed")
    ok("no look-ahead", True, f"all {len(YEARS)} policies price the same with the data cut on their own date")


def new_swap_is_flat(mkt):
    worst = max(abs(Policy(mkt, y).swap_margin()[0][1]) for y in YEARS)
    ok("a new swap is worth nothing", worst < 1e-9, f"largest value on the day struck {worst:.1e}")


def simulate_month(F, s, days_left, paths, rng):
    t = np.array(days_left)
    steps = np.diff(np.concatenate(([0.0], t)))
    z = rng.standard_normal((paths, len(t))) * np.sqrt(steps)
    w = np.cumsum(np.concatenate((z, -z)), axis=1)
    return F * np.exp(s * w - 0.5 * s * s * t)


def closed_form_against_simulation():
    rng = np.random.default_rng(7)
    worst = worst_delta = 0.0
    cases = [
        (2.0, 2.2, 0.35, 0.5, 0, 0.0),
        (2.0, 2.0, 0.60, 1.0, 0, 0.0),
        (4.0, 4.4, 0.30, 0.1, 0, 0.0),
        (3.0, 3.1, 0.40, 0.0, 10, 29.0),
        (3.0, 2.8, 0.50, 0.0, 15, 48.0),
    ]
    for F, K, s, lead, done, fixed in cases:
        n = done + (22 - done)
        t = [lead + (i + 1) / 260 for i in range(22 - done)]
        px = simulate_month(F, s, t, 150_000, rng)
        avg = (fixed + px.sum(axis=1)) / n
        pay = np.maximum(avg - K, 0)
        half = len(pay) // 2
        pairs = (pay[:half] + pay[half:]) / 2
        mc, se = pay.mean(), pairs.std(ddof=1) / math.sqrt(half)
        v, delta = asian_call(F, K, s, t, 1.0, done, fixed)
        worst = max(worst, abs(v - mc) / se)
        h = F * 1e-4
        fd = (asian_call(F + h, K, s, t, 1.0, done, fixed)[0] - asian_call(F - h, K, s, t, 1.0, done, fixed)[0]) / (2 * h)
        worst_delta = max(worst_delta, abs(fd - delta))
    ok("closed form against 300,000 paths", worst < 3.5, f"largest gap {worst:.1f} standard errors, months not begun and months under way")
    ok("delta is the slope of the value", worst_delta < 1e-5, f"largest gap {worst_delta:.1e}")


class ModelWorld(Market):
    """A market where the model is true: one price, constant volatility, no interest."""

    def __init__(self, seed, vol):
        rng = np.random.default_rng(seed)
        d, px, days = dt.date(2023, 1, 2), 2.0, []
        self.jet = {}
        while d <= dt.date(2025, 1, 31):
            if d.weekday() < 5:
                gap = max((d - days[-1]).days, 1) if days else 1
                px *= math.exp(vol * math.sqrt(gap / 365) * rng.standard_normal() - 0.5 * vol * vol * gap / 365)
                self.jet[d] = px
                days.append(d)
            d += dt.timedelta(days=1)
        self.ho = dict(self.jet)
        self.ulsd = dict(self.jet)
        self.brent_spot, self.eia, self.listed = {}, {}, {}
        self.bz, self.wti, self.ovx = {}, {}, {}
        self.rates = {days[0]: 0.0}
        self._index()
        self.market_vol = lambda _d: vol
        self.hedge_beta = lambda _d, _i: 1.0


def hedge_works_where_model_is_true():
    floor = model.SHAPE_FLOOR
    model.SHAPE_FLOOR = 1.0
    try:
        nets, prem = [], None
        for seed in range(80):
            p = Policy(ModelWorld(seed, 0.35), 2024, otm=OTM)
            res = desk.ledger(p, "ho")
            nets.append(res["net"])
            prem = res["premium"]
        nets = np.array(nets)
        err = abs(nets.mean()) / (nets.std(ddof=1) / math.sqrt(len(nets)))
        ok("the hedge works where the model is true", err < 3 and nets.std() < 0.35 * prem, f"mean result {nets.mean() / prem:+.1%} of premium, spread {nets.std() / prem:.0%} of premium, {len(nets)} simulated years")
    finally:
        model.SHAPE_FLOOR = floor


def ledger_adds_up(mkt):
    for y in SAMPLE:
        p = Policy(mkt, y, otm=OTM)
        a = desk.ledger(p, "ho", keep_path=True)
        last = a["path"][-1]
        if abs(last[1] - (a["premium"] + a["hedge"] - a["claims"])) > 1e-9:
            ok("the cash adds up", False, str(y))
        by_hand = 0.0
        for i, avg in enumerate(p.averages()):
            if p.last_fixing(i) is not None:
                by_hand += max(avg - p.K, 0)
        if abs(by_hand - a["claims"]) > 1e-9:
            ok("the claims add up", False, str(y))
    ok("the cash and the claims add up", True, f"{len(SAMPLE)} years rebuilt from the monthly averages")


def limit_does_what_it_says(mkt):
    for y in YEARS:
        a, b = Policy(mkt, y, otm=OTM), Policy(mkt, y, otm=OTM, limit=LIMIT)
        if b.premium > a.premium + 1e-12 or any(b.payoff(x) > LIMIT + 1e-12 for x in b.averages() if x is not None):
            ok("the limit", False, str(y))
    ok("the limit", True, "a limit never costs more and never pays more than itself")


def hindsight_costs_only_its_fee():
    """A cap at the swap rate must trail the better of swap and no hedge by exactly its fee."""
    res = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
    f = res["front"]
    fee = f["prices"]["market"]["hindsight"]
    gaps = [abs(s["regret"]["hindsight"] - fee) for s in f["scenarios"]]
    ok("hindsight costs its fee and nothing more", max(gaps) < 2e-4 and f["worst_regret"]["hindsight"] < min(f["worst_regret"]["none"], f["worst_regret"]["swap"]), f"regret ${fee:.3f} a gallon in all {len(gaps)} scenarios")


def by_a_second_road():
    """The April 2020 margin call again, from the CSV files, without model.py."""

    def table(name):
        with open(os.path.join(HERE, "data", name), encoding="utf-8") as f:
            return {r[0]: [float(x) for x in r[1:]] for r in list(csv.reader(f))[1:]}

    jet, fut, y1 = table("jet_usgc.csv"), table("heating_oil_futures.csv"), table("treasury_1y.csv")
    t0, day = "2019-12-31", "2020-04-27"
    d0, d1 = dt.date.fromisoformat(t0), dt.date.fromisoformat(day)
    ends = [month_end(2020, m) for m in range(1, 13)]
    df0 = [(1 + y1[t0][0] / 100) ** (-(e - d0).days / 365) for e in ends]
    c0 = fut[t0]
    fwd = [jet[t0][0] + c0[min(k, 4) - 1] - c0[0] for k in range(1, 13)]
    swap = sum(a * b for a, b in zip(df0, fwd)) / sum(df0)
    april = sorted(k for k in jet if k.startswith("2020-04"))
    done = [jet[k][0] for k in april if k <= day]
    value = 0.0
    for i, e in enumerate(ends):
        mo = i + 1
        if mo < 4:
            continue
        if mo == 4:
            days_in = max(22, len(april))
            f = (sum(done) + (days_in - len(done)) * jet[day][0]) / days_in
        else:
            f = fut[day][min(mo - 4, 4) - 1] + (jet[t0][0] - c0[0])
        value += (1 + y1[day][0] / 100) ** (-(e - d1).days / 365) * (f - swap)
    res = json.load(open(os.path.join(HERE, "results.json"), encoding="utf-8"))
    got = next(y for y in res["no_limit"] if y["year"] == 2020)["swap_call_back"]
    ok("the April 2020 margin call, by a second road", abs(-value * 10 - got["m"]) < 0.02 and got["on"] == day, f"${-value * 10:.2f}m against ${got['m']:.2f}m in the results")


def main():
    mkt = Market()
    sources_agree(mkt)
    contracts_roll_at_month_end(mkt)
    nothing_is_known_early(mkt)
    new_swap_is_flat(mkt)
    closed_form_against_simulation()
    hedge_works_where_model_is_true()
    ledger_adds_up(mkt)
    limit_does_what_it_says(mkt)
    hindsight_costs_only_its_fee()
    by_a_second_road()
    print("all checks passed")


if __name__ == "__main__":
    main()
