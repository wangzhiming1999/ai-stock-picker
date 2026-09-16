"""行情源并发闸门。

所有「按 code 逐只打行情源」的批量拉取都必须走 `gather_limited`。

为什么需要：腾讯历史 K 线是**按 code 逐只请求**的（见 `data_service._fetch_history`），
一句 `asyncio.gather(*(... for c in codes))` 会在毫秒内对同一个出口 IP 甩出几十个请求。
而「今日作战」首屏自身就会并发拉起简报 / 推荐 / 推衍三批数据，各路并发叠加后极易触发
行情源的 IP 级风控（实测 30 并发直打 → `Connection aborted`，随后全站 502 数分钟）。

为什么用进程级信号量而不是每次调用新建一个：配额是绑在**出口 IP** 上的，不是绑在单次请求上的。
每个请求各拿一个 `Semaphore(8)` 并不能保护 IP，只会把上限变成 8 × 并发请求数。

⚠️ 禁止嵌套：信号量只包裹「叶子 I/O」（`asyncio.to_thread(data_service.xxx, ...)`）。
若被包裹的调用自身又去 `gather_limited`，两者会互相等待造成死锁。
"""
import asyncio
import weakref
from collections.abc import Awaitable, Iterable
from contextlib import asynccontextmanager
from typing import TypeVar

T = TypeVar("T")

# 单批并发上限。取值依据：免费公开行情源容忍度低，实测 30 并发即触发断连；
# 8 并发下 30 只票约 4 轮完成，叠加各服务已有缓存（日线成功缓存 5min / 失败 30s），
# 额外耗时在秒级，换来的是不再触发 IP 级风控。
FETCH_CONCURRENCY = 8

# 按 event loop 缓存信号量：生产环境 FastAPI 只有一个 loop，等价于进程级配额；
# 测试里每个用例会新建 loop，按 loop 隔离可避免「Semaphore 绑定了另一个 loop」报错。
_semaphores: "weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    weakref.WeakKeyDictionary()
)


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _semaphores.get(loop)
    if sem is None:
        sem = asyncio.Semaphore(FETCH_CONCURRENCY)
        _semaphores[loop] = sem
    return sem


async def gather_limited(
    awaitables: Iterable[Awaitable[T]],
    limit: int | None = None,
    return_exceptions: bool = False,
) -> list:
    """带并发上限的 `asyncio.gather`，返回顺序与入参严格一致。

    limit 传 None 时使用全局上限 `FETCH_CONCURRENCY`（推荐，走进程级共享配额）；
    显式传值则使用该次调用独立的上限（仅供特殊场景，不要用来绕过风控）。
    """
    items = list(awaitables)
    if not items:
        return []
    sem = asyncio.Semaphore(max(1, limit)) if limit else _semaphore()

    async def _run(aw: Awaitable[T]) -> T:
        async with sem:
            return await aw

    return await asyncio.gather(*(_run(aw) for aw in items), return_exceptions=return_exceptions)


@asynccontextmanager
async def limited(limit: int | None = None):
    """占一个并发配额执行一段叶子 I/O，供「单只票要连打好几个接口」的场景使用。

    ⚠️ 不可与 `gather_limited` 互相嵌套 —— 只会各占一个配额或直接死锁。
    """
    sem = asyncio.Semaphore(max(1, limit)) if limit else _semaphore()
    async with sem:
        yield
