"""测试每日推荐接口。"""
import httpx

r = httpx.get("https://backend-smoky-kappa-70.vercel.app/api/market/daily-recommend", timeout=120)
print("status:", r.status_code)
data = r.json()
print("source:", data.get("source"))
print("candidates:", data.get("candidates"))
print("recs:", len(data.get("recommendations", [])))
print("message:", data.get("message", ""))
for rec in data.get("recommendations", [])[:3]:
    print(f"  {rec['name']}({rec['code']}) 置信{rec['confidence']} {rec['reason'][:50]}")
