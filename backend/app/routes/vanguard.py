"""决策先锋路由：三维选股榜与单票诊股。

两条路径刻意分开，因为成本完全不同：
- `/vanguard` 是**整榜**（每日懒生成 + DB 快照缓存），首次生成会拉一次资金流批次
  与数十只 K 线，之后当天全部命中缓存；
- `/vanguard/diagnose` 是**单票**，优先复用榜单里已有的结果（零额外请求），
  不在榜内才现场算两只接口。前端应在用户显式操作时才调用它，不要轮询。
"""
from fastapi import APIRouter, HTTPException

from app.services import vanguard_service

router = APIRouter(prefix="/api/market", tags=["vanguard"])


@router.get("/vanguard")
async def vanguard_board(refresh: bool = False):
    """决策先锋三维榜：暗盘资金 / 趋势 / 活跃度 打分排序。

    同屏还带板块强度、主力抱团、潜力龙头与买卖时机（结构位）。

    ⚠️ 返回体的 `evidence.tier` 恒为 `preliminary`（三维分是当日读数，不是收益口径，
    从未跑过收益回测）。调用方**不得**把它渲染成买点或动作指令。

    refresh=true 现在会**穿透底层行情源**（force=True）：跳过内存 / Supabase 两层快照直拉全市场，
    并一并穿透资金流批次与本服务榜单缓存。底层直拉受 `_get_spot` 的跨实例冷却（180s）与
    最小间隔（60s）守卫，触发风控会转成 502 + 冷却文案；前端 refresh 按钮因此必须走 `spotGuard`
    的二次确认 + 冷却倒计时，禁止连点。
    """
    try:
        return await vanguard_service.get_board(force_refresh=refresh)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"决策先锋榜生成失败: {e}")


@router.get("/vanguard/diagnose")
async def vanguard_diagnose(code: str):
    """单票三维体检（诊股）：三维分 + 结构位 + 所属板块强度。

    与全局的「深度分析」（LLM 多角色辩论）分工不同 —— 这里只给量化读数，不给多空结论。
    """
    if not code or not code.strip():
        raise HTTPException(status_code=400, detail="缺少股票代码")
    try:
        return await vanguard_service.diagnose(code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"诊股失败: {e}")
