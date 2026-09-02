"""验证回测持久化：跑一次写库，再查库是否秒回。"""
import time

import httpx

url = "https://backend-smoky-kappa-70.vercel.app/api/backtest/run"
body = {"strategy": "momentum", "start_date": "2025-01-01", "top_n": 5, "rebalance_days": 5}

t0 = time.time()
r = httpx.post(url, json=body, timeout=120)
t1 = time.time()
print(f"1st backtest: {t1-t0:.1f}s status={r.status_code}")

t2 = time.time()
r2 = httpx.post(url, json=body, timeout=30)
t3 = time.time()
print(f"2nd backtest (db cache): {t3-t2:.1f}s status={r2.status_code}")
