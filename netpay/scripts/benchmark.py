"""Naive vs greedy vs exact: payment counts and runtime. Use the output in your demo."""
import random, time
from netpay import Obligation, build_plan, net_balances, greedy_settle, exact_settle


def make_obligations(n_parties, n_obs, seed):
    rng = random.Random(seed)
    parties = [f"P{i}" for i in range(n_parties)]
    obs = []
    for i in range(n_obs):
        d, c = rng.sample(parties, 2)
        obs.append(Obligation(str(i), d, c, rng.randint(100, 100_000)))
    return obs


if __name__ == "__main__":
    print(f"{'parties':>8} {'invoices':>9} {'naive':>6} {'greedy':>7} {'exact':>6} {'greedy ms':>10} {'exact ms':>9}")
    for n, m in [(6, 20), (10, 40), (14, 60), (16, 80)]:
        obs = make_obligations(n, m, seed=n)
        bal = {k: v for k, v in net_balances(obs).items() if v}
        t = time.perf_counter(); g = greedy_settle(bal); tg = (time.perf_counter() - t) * 1000
        t = time.perf_counter(); e = exact_settle(bal); te = (time.perf_counter() - t) * 1000
        print(f"{n:>8} {m:>9} {len(obs):>6} {len(g):>7} {len(e):>6} {tg:>10.2f} {te:>9.1f}")
