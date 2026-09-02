"""用 API 验证持仓完整流程（对应前端 UI 的逻辑）。"""
import httpx

BASE = "https://backend-smoky-kappa-70.vercel.app"

r = httpx.post(f"{BASE}/api/auth/signin", json={"email": "holdtest@example.com", "password": "Test123456"}, timeout=30)
token = r.json()["access_token"]
h = {"Authorization": f"Bearer {token}"}

# 持仓列表（应返回之前测试添加的）
r = httpx.get(f"{BASE}/api/portfolio/holdings", headers=h, timeout=30)
print("holdings:", r.status_code)
d = r.json()
print("  count:", len(d.get("holdings", [])))
print("  total_value:", d.get("total_value"), "total_pnl:", d.get("total_pnl"), "total_pnl_pct:", d.get("total_pnl_pct"))

# 建议
r = httpx.get(f"{BASE}/api/portfolio/advice", headers=h, timeout=60)
print("advice:", r.status_code)
a = r.json()
print("  risk:", a.get("risk_level"))
print("  tips:", a.get("portfolio_tips", [])[:2])
for x in a.get("holdings_advice", [])[:2]:
    print(f"  {x['name']}: action={x['action']} pos={x['position_pct']}% rr={x['rr_ratio']} tips={x['tips'][:2]}")

# 更新持仓
r = httpx.put(f"{BASE}/api/portfolio/holdings/2", json={"shares": 800}, headers=h, timeout=30)
print("update:", r.status_code, r.text[:80])
