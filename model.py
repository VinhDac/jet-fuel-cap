"""Jet fuel price protection: the market, the pricing, and the swap it is compared with.

The policy. For each month of a year it pays max(average - K, 0) a gallon on that month's
average jet price, up to a limit. The premium is paid once, at the start.

The forward curve. Gulf Coast jet trades as a differential to the NYMEX heating oil (ULSD)
future, so a delivery month is priced as today's jet price plus the slope of the futures
curve. To April 2024 the curve is EIA's four contracts. After that it is the front contract
and every later contract month still listed, with straight lines between them.

The volatility. One factor, lognormal. No public option quote exists for jet or heating oil,
so the level is built from what is public: heating oil's front contract over the last 252
days, moved by how far crude's implied volatility (OVX) now stands from its own 252-day mean,
times IMPLIED_OVER_REALISED, what crude options have cost against what crude then did. The
term structure comes from `shape`, and a forward's volatility is the time-average, in
variance, of the tenors it rolls through.
"""
import csv
import datetime as dt
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
DAYS_A_YEAR = 365.0
VOL_WINDOW = 252
GALLONS_A_BARREL = 42.0
IMPLIED_OVER_REALISED = 1.07  # calibrate.py
SHAPE_FLOOR, SHAPE_DECAY = 0.49, 0.10  # calibrate.py
MARGIN_Z, MARGIN_DAYS, MARGIN_LAMBDA = 2.33, 2, 0.97  # a 99% two-day move, on a slow average


def shape(k):
    """A contract k months from delivery, as a share of the front contract's volatility."""
    return SHAPE_FLOOR + (1 - SHAPE_FLOOR) * math.exp(-SHAPE_DECAY * (max(k, 1) - 1))


def rolled_shape(k):
    """The same for a forward that will roll down through tenors k, k-1, ... 1."""
    return math.sqrt(sum(shape(j) ** 2 for j in range(1, max(k, 1) + 1)) / max(k, 1))


def _read(name, until):
    with open(os.path.join(DATA, name), encoding="utf-8") as f:
        rows = list(csv.reader(f))[1:]
    out = {}
    for r in rows:
        d = dt.date.fromisoformat(r[0])
        if until is None or d <= until:
            out[d] = [float(x) for x in r[1:]]
    return out


def _one(name, until):
    return {d: v[0] for d, v in _read(name, until).items()}


def month_index(y, m):
    return y * 12 + m - 1


def month_end(y, m):
    return (dt.date(y + (m == 12), m % 12 + 1, 1)) - dt.timedelta(days=1)


def weekdays(y, m):
    d, end, out = dt.date(y, m, 1), month_end(y, m), []
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def norm_cdf(x):
    return 0.5 * math.erfc(-x / math.sqrt(2))


def discount(y, t):
    return (1 + y) ** (-t)


class Market:
    def __init__(self, until=None):
        """All the data, cut at `until` if given: what could be known on that day."""
        self.jet = _one("jet_usgc.csv", until)
        self.ulsd = _one("ulsd_nyh.csv", until)
        self.brent_spot = _one("brent.csv", until)
        self.eia = _read("heating_oil_futures.csv", until)
        self.ho = _one("market/ho_front.csv", until)
        self.bz = _one("market/brent_front.csv", until)
        self.wti = _one("market/wti_front.csv", until)
        self.ovx = _one("market/ovx.csv", until)
        self.rates = {d: v / 100 for d, v in _one("treasury_1y.csv", until).items()}
        self.listed = {}
        with open(os.path.join(DATA, "market", "ho_contracts.csv"), encoding="utf-8") as f:
            for d, deliv, close in list(csv.reader(f))[1:]:
                day = dt.date.fromisoformat(d)
                if until is None or day <= until:
                    y, m = deliv.split("-")
                    self.listed.setdefault(month_index(int(y), int(m)), {})[day] = float(close)
        self._index()

    def _index(self):
        self.days = sorted(d for d in self.jet if d in self.ho)
        self.rate_days = sorted(self.rates)
        self.fixings = {}
        for d in sorted(self.jet):
            self.fixings.setdefault((d.year, d.month), []).append((d, self.jet[d]))
        self.dh, self.rh = self._changes(self.ho, self._ho_roll)
        self.db, self.rb = self._changes(self.bz, self._bz_roll)
        self.ew_h = self._ewma(self.rh)
        self.ew_b = self._ewma(self.rb)
        self._curves, self._betas, self._vols = {}, {}, {}
        self._rh_days = sorted(self.rh)
        self._ew_days = {"ho": sorted(self.ew_h), "brent": sorted(self.ew_b)}
        self._ovx_days = sorted(self.ovx)

    def _ho_roll(self, p, q):
        """The move of one contract across the turn of the month, when the front changes."""
        if p in self.eia and q in self.eia:
            return self.eia[q][0] - self.eia[p][1]
        if p in self.ulsd and q in self.ulsd:
            return self.ulsd[q] - self.ulsd[p]
        return None

    def _bz_roll(self, p, q):
        if p in self.wti and q in self.wti and self.wti[p] > 5:
            return (self.wti[q] - self.wti[p]) * self.bz[p] / self.wti[p]
        return None

    @staticmethod
    def _changes(px, roll):
        """Each day's change and log return in one contract, never across a contract change."""
        days = sorted(px)
        dollars, logs = {}, {}
        for p, q in zip(days, days[1:]):
            if (q - p).days > 5 or px[p] <= 0:
                continue
            change = roll(p, q) if (p.year, p.month) != (q.year, q.month) else px[q] - px[p]
            if change is None or px[p] + change <= 0:
                continue
            dollars[q] = change
            logs[q] = math.log((px[p] + change) / px[p])
        return dollars, logs

    @staticmethod
    def _ewma(rets):
        out, v = {}, None
        for d in sorted(rets):
            r2 = rets[d] ** 2
            v = r2 if v is None else MARGIN_LAMBDA * v + (1 - MARGIN_LAMBDA) * r2
            out[d] = v
        return out

    def margin_vol(self, d, instrument):
        """The slow daily volatility of the instrument, as of day d."""
        table = self.ew_h if instrument == "ho" else self.ew_b
        days = self._ew_days[instrument]
        return math.sqrt(table[days[max(int(np.searchsorted(days, d, side="right")) - 1, 0)]])

    def rate(self, d):
        if d in self.rates:
            return self.rates[d]
        i = np.searchsorted(self.rate_days, d, side="right") - 1
        return self.rates[self.rate_days[max(i, 0)]]

    def front_vol(self, d):
        if d not in self._vols:
            days = self._rh_days[: int(np.searchsorted(self._rh_days, d, side="right"))][-VOL_WINDOW:]
            self._vols[d] = float(np.std([self.rh[x] for x in days], ddof=1) * math.sqrt(252))
        return self._vols[d]

    def market_vol(self, d):
        """The front contract's volatility as an option market would put it on day d."""
        i = int(np.searchsorted(self._ovx_days, d, side="right"))
        recent = [self.ovx[x] for x in self._ovx_days[max(i - VOL_WINDOW, 0):i]]
        moved = recent[-1] / float(np.mean(recent)) if recent else 1.0
        return self.front_vol(d) * IMPLIED_OVER_REALISED * moved

    def curve(self, d):
        """Heating oil by delivery month, as (month indices, prices), on day d."""
        if d not in self._curves:
            m = month_index(d.year, d.month)
            if d in self.eia:
                xs, ys = [m + k for k in range(1, 5)], list(self.eia[d])
            else:
                xs, ys = [m + 1], [self.ho[d]]
            for idx in sorted(self.listed):
                c = self.listed[idx]
                if idx > xs[-1] and d in c:
                    xs.append(idx)
                    ys.append(c[d])
            self._curves[d] = (np.array(xs, dtype=float), np.array(ys, dtype=float))
        return self._curves[d]

    def jet_forward(self, d, y, m):
        """The jet price for delivery month (y, m), seen on day d, before that month."""
        xs, ys = self.curve(d)
        return self.jet[d] + float(np.interp(month_index(y, m), xs, ys)) - float(ys[0])

    def differential(self, d):
        return self.jet[d] - float(self.curve(d)[1][0])

    def hedge_date(self, year):
        return max(x for x in self.days if x < dt.date(year, 1, 1))

    def hedge_beta(self, d, instrument):
        """Dollars of jet per dollar of the instrument (a gallon's worth), last 252 days."""
        key = (d.year, d.month, instrument)
        if key not in self._betas:
            ch, scale = (self.dh, 1.0) if instrument == "ho" else (self.db, GALLONS_A_BARREL)
            days = sorted(self.jet)
            pairs = []
            for p, q in zip(days, days[1:]):
                if q <= d and q in ch and (q - p).days <= 5:
                    pairs.append((self.jet[q] - self.jet[p], ch[q] / scale))
            a = np.array(pairs[-VOL_WINDOW:])
            c = np.cov(a[:, 0], a[:, 1])
            self._betas[key] = float(c[0, 1] / c[1, 1])
        return self._betas[key]


def asian_call(F, K, sigma, t, df, done=0, fixed_sum=0.0):
    """A cap on a month's average: value and delta to the forward, per gallon.

    `t` holds the years to the fixings still to come, in order; `done` fixings have happened,
    adding to `fixed_sum`. The rest of the month is matched to a lognormal.
    """
    r = len(t)
    n = done + r
    if r == 0:
        return df * max(fixed_sum / n - K, 0.0), 0.0
    weight = r / n
    k = (n * K - fixed_sum) / r
    if k <= 0:
        return df * weight * (F - k), df * weight
    total = 0.0
    for i, x in enumerate(t):
        total += (2 * (r - 1 - i) + 1) * math.exp(sigma * sigma * max(x, 0.0))
    v = max(math.log(total / (r * r)), 1e-12)
    root = math.sqrt(v)
    d1 = (math.log(F / k) + v / 2) / root
    Nd1 = norm_cdf(d1)
    return df * weight * (F * Nd1 - k * norm_cdf(d1 - root)), df * weight * Nd1


class Policy:
    """Cover for the twelve months of `year`, priced on day t0 (by default the last day before it)."""

    def __init__(self, mkt, year, t0=None, strike=None, otm=0.10, limit=None, vol_scale=1.0):
        self.mkt, self.year, self.limit = mkt, year, limit
        self.t0 = t0 or mkt.hedge_date(year)
        self.y0 = mkt.rate(self.t0)
        self.base_vol = mkt.market_vol(self.t0) * vol_scale
        self.fix_days = [weekdays(year, m) for m in range(1, 13)]
        self.ends = [month_end(year, m) for m in range(1, 13)]
        self.T = [(e - self.t0).days / DAYS_A_YEAR for e in self.ends]
        self.df = np.array([discount(self.y0, x) for x in self.T])
        self.F = np.array([mkt.jet_forward(self.t0, year, m) for m in range(1, 13)])
        self.S = float((self.df * self.F).sum() / self.df.sum())
        self.K = float(strike) if strike is not None else self.S * (1 + otm)
        self.top = None if limit is None else self.K + limit
        self._legs = {}
        self.caplets = np.array([self._leg_value(self.t0, i, self.F[i], self.df[i])[0] for i in range(12)])

    def tenor(self, d, i):
        return month_index(self.year, i + 1) - month_index(d.year, d.month)

    def sigma(self, d, i):
        return self.base_vol * rolled_shape(self.tenor(d, i))

    def _leg_value(self, d, i, F, df, done=0, fixed=0.0):
        t = [(x - d).days / DAYS_A_YEAR for x in self.fix_days[i] if x > d]
        s = self.sigma(d, i)
        if done:
            # the weekdays still to come, and the fixings that have been published so far
            n = len(self.fix_days[i])
            done = n - len(t)
        v, delta = asian_call(F, self.K, s, t, df, done, fixed)
        if self.top is not None:
            v2, d2 = asian_call(F, self.top, s, t, df, done, fixed)
            v, delta = v - v2, delta - d2
        return v, delta

    @property
    def premium(self):
        """Per gallon of the year's volume (the mean over the twelve months)."""
        return float(self.caplets.mean())

    def averages(self):
        out = []
        for m in range(1, 13):
            fx = self.mkt.fixings.get((self.year, m))
            out.append(float(np.mean([p for _, p in fx])) if fx else None)
        return out

    def payoff(self, avg):
        p = max(avg - self.K, 0.0)
        return min(p, self.limit) if self.limit is not None else p

    def open_legs(self, d):
        """Value and hedge delta of the months not yet settled, on day d."""
        if d in self._legs:
            return self._legs[d]
        mkt, value, legs = self.mkt, 0.0, []
        y = mkt.rate(d)
        for i in range(12):
            end = self.ends[i]
            last = self.last_fixing(i)
            if last is not None and d >= last:
                continue
            df = discount(y, max((end - d).days, 0) / DAYS_A_YEAR)
            if d.year == self.year and d.month == i + 1:
                fix = [(x, p) for x, p in mkt.fixings[(self.year, i + 1)] if x <= d]
                v, delta = self._leg_value(d, i, mkt.jet[d], df, done=max(len(fix), 1), fixed=self._scaled_sum(i, fix))
            else:
                v, delta = self._leg_value(d, i, mkt.jet_forward(d, self.year, i + 1), df)
            value += v
            legs.append((i, delta))
        self._legs[d] = (value, legs)
        return value, legs

    def _scaled_sum(self, i, fix):
        """Fixings so far, stood for the weekdays passed (a holiday repeats the month's mean so far)."""
        if not fix:
            return 0.0
        n_passed = sum(1 for x in self.fix_days[i] if x <= fix[-1][0])
        return float(np.mean([p for _, p in fix])) * n_passed

    def last_fixing(self, i):
        """The month's last published price, if the month is over in the data."""
        fx = self.mkt.fixings.get((self.year, i + 1))
        if not fx or self.mkt.days[-1] <= self.ends[i] and fx[-1][0] == self.mkt.days[-1]:
            return None
        return fx[-1][0]

    def swap_margin(self):
        """Each day: what a swap at S is worth to the airline, a gallon a month, marked two ways.

        Held: the jet differential stays where it is. Back: it returns to its level on t0.
        """
        mkt, out = self.mkt, []
        d0 = mkt.differential(self.t0)
        for d in mkt.days:
            if d < self.t0 or d.year > self.year:
                continue
            y = mkt.rate(d)
            held = back = 0.0
            for i in range(12):
                end = self.ends[i]
                if d > end:
                    continue
                df = discount(y, (end - d).days / DAYS_A_YEAR)
                if d.year == self.year and d.month == i + 1:
                    fx = mkt.fixings[(self.year, i + 1)]
                    done = [p for x, p in fx if x <= d]
                    days_in = max(len(self.fix_days[i]), len(fx))
                    f = g = (sum(done) + (days_in - len(done)) * mkt.jet[d]) / days_in
                else:
                    f = mkt.jet_forward(d, self.year, i + 1)
                    g = f - mkt.differential(d) + d0
                held += df * (f - self.S)
                back += df * (g - self.S)
            out.append((d, held, back))
        return out
