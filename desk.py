"""The other side of the policy: what the seller's cash does if it hedges in listed futures.

Each day: the hedge is marked (variation margin in or out), a month that has ended is paid,
the position is reset to the policy's delta, and initial margin is held against it.

    cash = premium + variation margin so far - claims paid so far - initial margin today

The position is in the front contract. A delivery month further out moves less than the front
(`shape`), and jet does not move one for one with the instrument (`hedge_beta`).
Initial margin is a rule, not the exchange's schedule: a 99% two-day move, on a slow average.
"""
import math

from model import GALLONS_A_BARREL, MARGIN_DAYS, MARGIN_Z, shape

VOLUME_M = 10.0  # million gallons a month: per-gallon figures times this are $m


def margin_rate(mkt, d, instrument):
    return MARGIN_Z * math.sqrt(MARGIN_DAYS) * mkt.margin_vol(d, instrument)


def instrument_price(mkt, d, instrument):
    return mkt.ho[d] if instrument == "ho" else mkt.bz[d] / GALLONS_A_BARREL


def instrument_change(mkt, d, instrument):
    if instrument == "ho":
        return mkt.dh.get(d)
    c = mkt.db.get(d)
    return None if c is None else c / GALLONS_A_BARREL


def ledger(policy, instrument="ho", loading=0.0, keep_path=False):
    """Run one policy from sale to the end of its year, or to the last day of data.

    With instrument=None the book is left unhedged. Results are per gallon a month.
    """
    mkt = policy.mkt
    premium = float(policy.caplets.sum()) * (1 + loading)
    days = [d for d in mkt.days if policy.t0 <= d and d.year <= policy.year]
    if instrument == "brent":
        days = [d for d in days if d in mkt.bz]
    position = 0.0
    vm = claims = 0.0
    low_cash, peak_im, low_vm = (premium, policy.t0), (0.0, policy.t0), (0.0, policy.t0)
    path = []
    settled = set()
    open_value = 0.0
    for d in days:
        if instrument and d != policy.t0:
            change = instrument_change(mkt, d, instrument)
            if change is not None:
                vm += position * change
        for i in range(12):
            last = policy.last_fixing(i)
            if i not in settled and last is not None and d >= last:
                fx = mkt.fixings[(policy.year, i + 1)]
                claims += policy.payoff(sum(p for _, p in fx) / len(fx))
                settled.add(i)
        open_value, legs = policy.open_legs(d)
        im = 0.0
        position = 0.0
        if instrument:
            beta = mkt.hedge_beta(d, instrument)
            for i, delta in legs:
                position += delta * shape(policy.tenor(d, i)) * beta
            im = margin_rate(mkt, d, instrument) * instrument_price(mkt, d, instrument) * abs(position)
        cash = premium + vm - claims - im
        if cash < low_cash[0]:
            low_cash = (cash, d)
        if im > peak_im[0]:
            peak_im = (im, d)
        if vm < low_vm[0]:
            low_vm = (vm, d)
        if keep_path:
            path.append((d, premium + vm - claims, im, claims, vm))
    return {
        "premium": premium,
        "claims": claims,
        "hedge": vm,
        "open_liability": open_value,
        "net": premium + vm - claims - open_value,
        "low_cash": low_cash,
        "peak_im": peak_im,
        "low_vm": low_vm,
        "path": path,
    }
