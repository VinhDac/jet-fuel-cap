"""Break each rule on a copy of this folder, and see a check fail.

A check nobody has seen fail proves little. Run: python mutations.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))

MUTATIONS = [
    ("the futures read a day late", "model.py",
     'self.eia = _read("heating_oil_futures.csv", until)',
     'self.eia = _read("heating_oil_futures.csv", until); f = sorted(self.eia); self.eia = {b: self.eia[a] for a, b in zip(f, f[1:])}'),
    ("forwards a month out", "model.py",
     "float(np.interp(month_index(y, m), xs, ys))", "float(np.interp(month_index(y, m) + 1, xs, ys))"),
    ("volatility sees the future", "model.py",
     'days = self._rh_days[: int(np.searchsorted(self._rh_days, d, side="right"))][-VOL_WINDOW:]', "days = self._rh_days[-VOL_WINDOW:]"),
    ("implied volatility sees the future", "model.py",
     'i = int(np.searchsorted(self._ovx_days, d, side="right"))', 'i = int(np.searchsorted(self._ovx_days, d, side="right")) + 5'),
    ("swap rate off the curve", "model.py",
     "self.S = float((self.df * self.F).sum() / self.df.sum())", "self.S = float(self.F.mean() * 1.01)"),
    ("no averaging in the closed form", "model.py",
     "v = max(math.log(total / (r * r)), 1e-12)", "v = sigma * sigma * max(t)"),
    ("delta too small", "model.py",
     "return df * weight * (F * Nd1 - k * norm_cdf(d1 - root)), df * weight * Nd1",
     "return df * weight * (F * Nd1 - k * norm_cdf(d1 - root)), df * weight * Nd1 * 0.9"),
    ("a limit that adds value", "model.py", "v, delta = v - v2, delta - d2", "v, delta = v + v2, delta - d2"),
    ("a limit that does not bind", "model.py",
     "return min(p, self.limit) if self.limit is not None else p", "return p"),
    ("margin ignores the fixings so far", "model.py",
     "f = g = (sum(done) + (days_in - len(done)) * mkt.jet[d]) / days_in", "f = g = mkt.jet[d]"),
    ("the hedge is too small", "desk.py",
     "position += delta * shape(policy.tenor(d, i)) * beta", "position += delta * shape(policy.tenor(d, i)) * beta * 0.6"),
    ("claims paid on the month's high", "desk.py",
     "claims += policy.payoff(sum(p for _, p in fx) / len(fx))", "claims += policy.payoff(max(p for _, p in fx))"),
    ("the ledger forgets the premium", "desk.py",
     "path.append((d, premium + vm - claims, im, claims, vm))", "path.append((d, vm - claims, im, claims, vm))"),
    ("the hindsight fee is left out", "backtest.py",
     '"hindsight": min(a, base.S) + h,', '"hindsight": min(a, base.S),'),
]


def run(item):
    name, fname, old, new = item
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        copy = os.path.join(tmp, "study")
        shutil.copytree(HERE, copy, ignore=shutil.ignore_patterns("__pycache__", ".git", "site"))
        path = os.path.join(copy, fname)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        if old not in text:
            return False, f"NOT APPLIED  {name}"
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text.replace(old, new))
        first = subprocess.run([sys.executable, "backtest.py"], cwd=copy, capture_output=True, text=True)
        second = subprocess.run([sys.executable, "checks.py"], cwd=copy, capture_output=True, text=True)
        red = [line for line in second.stdout.splitlines() if line.startswith("FAIL")]
        if first.returncode == 0 and red:
            return True, f"caught  {name}: {red[0][6:]}"
        return False, f"MISSED  {name}: {(first.stderr or second.stderr)[-200:]}"


def main():
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, MUTATIONS))
    for _, line in results:
        print(line, flush=True)
    missed = sum(1 for good, _ in results if not good)
    print("every rule broken was caught" if not missed else f"{missed} not caught")
    sys.exit(1 if missed else 0)


if __name__ == "__main__":
    main()
