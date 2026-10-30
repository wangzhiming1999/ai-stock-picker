"""一次性回填：把 daily_recommend_snapshots.result 里的信号时快照补到 daily_recommendations。

## 背景

旧行/漏写行没有 `feature_snapshot`。本脚本从 `daily_recommend_snapshots.result` 的
`recommendations[*]` / `watchlist[*]` 里找 `feature_snapshot` 补到同 (rec_date, code) 行——
**只补空、不覆盖、v8 之前无此字段不伪造**。

⚠️ 2026-10-30 生产实测（dry-run + 实跑）：**0 行可回填**。历史快照的 recs 从未存过
`feature_snapshot`（git 实证：`build_feature_snapshot` 进 recs 是 V5.44 `e46d664` 才加的；
快照 watchlist 条目也不带）。脚本只对 V5.44 之后「快照存了 recs 但 daily_recommendations
写失败/降级」的窗口有恢复价值，历史旧行留空是既定事实，不属本脚本可补范围。

## 红线

* v8 之前的快照里没有 feature_snapshot 字段 → **不回填、不伪造**，保持空。
* 已有非空 feature_snapshot 的行**不覆盖**（只补空）。
* 写路径逐行容错：单行失败不中断整轮，错误汇总打印。

用法（backend/ 目录下）：
    py scripts/backfill_feature_snapshot.py            # 执行回填
    py scripts/backfill_feature_snapshot.py --dry-run  # 只统计不动库
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import supabase_store


def _snapshot_of(rec: dict) -> dict:
    snap = rec.get("feature_snapshot") or {}
    return snap if isinstance(snap, dict) and any(v is not None for v in snap.values()) else {}


async def _iter_snapshot_pages(sb, page_size: int = 200):
    start = 0
    while True:
        response = (
            await sb.table("daily_recommend_snapshots")
            .select("rec_date, result")
            .range(start, start + page_size - 1)
            .execute()
        )
        page = response.data or []
        for row in page:
            yield row
        if len(page) < page_size:
            return
        start += page_size


async def run(dry_run: bool = False) -> dict:
    if not supabase_store.is_configured():
        print("Supabase 未配置，无法回填")
        return {"status": "storage_not_configured"}

    sb = await supabase_store.get_service_client()
    stats = {
        "snapshot_days": 0,
        "source_recs": 0,
        "rows_with_empty_snapshot": 0,
        "backfilled": 0,
        "skipped_existing": 0,
        "skipped_no_source": 0,
        "errors": [],
    }

    async for snap_row in _iter_snapshot_pages(sb):
        rec_date = snap_row.get("rec_date")
        result = snap_row.get("result") or {}
        recs = (result.get("recommendations") or []) + (result.get("watchlist") or [])
        source = {str(rec.get("code")): _snapshot_of(rec) for rec in recs if rec.get("code")}
        source = {code: snap for code, snap in source.items() if snap}
        if not rec_date or not source:
            continue
        stats["snapshot_days"] += 1
        stats["source_recs"] += len(source)

        try:
            existing = (
                await sb.table("daily_recommendations")
                .select("id, code, feature_snapshot")
                .eq("rec_date", rec_date)
                .execute()
            )
        except Exception as error:
            stats["errors"].append(f"{rec_date} 读取失败: {type(error).__name__}: {error}")
            continue

        for row in existing.data or []:
            code = str(row.get("code") or "")
            snapshot = source.get(code)
            if not code or not snapshot:
                continue
            if (row.get("feature_snapshot") or {}) and any(
                v is not None for v in (row.get("feature_snapshot") or {}).values()
            ):
                stats["skipped_existing"] += 1
                continue
            stats["rows_with_empty_snapshot"] += 1
            if dry_run:
                stats["backfilled"] += 1
                continue
            try:
                await (
                    sb.table("daily_recommendations")
                    .update({"feature_snapshot": snapshot})
                    .eq("id", row["id"])
                    .execute()
                )
                stats["backfilled"] += 1
            except Exception as error:
                stats["errors"].append(
                    f"{rec_date}/{code} 补写失败: {type(error).__name__}: {error}"
                )
        stats["skipped_no_source"] += max(
            0, len(existing.data or []) - stats["rows_with_empty_snapshot"] - stats["skipped_existing"]
        )

    stats["status"] = "dry_run" if dry_run else "done"
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args()
    stats = asyncio.run(run(dry_run=args.dry_run))
    for key, value in stats.items():
        if key == "errors":
            continue
        print(f"{key}: {value}")
    for error in stats.get("errors", []):
        print(f"[error] {error}")
    if stats.get("errors"):
        sys.exit(1)


if __name__ == "__main__":
    main()
