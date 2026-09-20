"""建表 SQL 覆盖守卫。

修复背景（2026-09-20 技术债清理）：
`quad_snapshots` 与 `daily_recommend_snapshots` 是 quad / 推荐链路的持久化底座，
当年在 Supabase 控制台手动建表，**仓库里从来没有对应的建表 SQL**。后果不是
「读不到缓存」这么轻，是**改不了** —— 想加列、加索引、调类型时，没有任何文件
能作为「线上到底是什么结构」的依据，只能猜或连生产库看。

补 v11 时顺手全量盘了一次，发现缺口比记录的更大：一共 10 张表没有建表 SQL
（其中 2 张已补进 v11，剩余 8 张见 `KNOWN_MISSING`）。

本文件把「代码引用到的表必须有建表文件」变成一条断言，规则双向生效：
- 新表被代码引用却没 SQL → 失败；
- `KNOWN_MISSING` 里的表补上了 SQL 却没从清单删掉 → 也失败（清单必须保持真实）。

另外守卫两件容易出事的小事：迁移文件必须幂等（重跑不失败），
以及 `supabase-schema-all.sql` 这个手工合并副本不能被误当成迁移链的一部分。

最后还守卫 `/api/admin/migrate/status` 的自检清单：那份清单曾把两张**毫无代码引用**的
历史表名（`portfolio_holdings` / `watchlist`）当作「预期表」，自检于是永远报缺失。
"""

import pathlib
import re
import unittest

BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
APP_DIR = BACKEND_DIR / "app"

BASE_SCHEMA = "supabase-schema.sql"
# 与 routes/admin.py `_ordered_schema_files()` 的 glob 保持一致 —— 只有这些会被真正执行
MIGRATION_GLOB = "supabase-schema-v*.sql"
# v4+v5+v6 的手工合并副本：文件头自己写明「保留仅为一次性全量执行提供便利」，
# 且**不在**自动迁移 glob 里。它能被读，但不能被当作结构依据（会与拆分版本漂移）。
MERGED_LEGACY = "supabase-schema-all.sql"

# 代码引用但全仓无建表 SQL 的表。
# ⚠️ 列定义**故意不手写**：这些表早已存在于线上，靠读代码反推列类型等于编造结构记录，
#    比没有更危险（`CREATE TABLE IF NOT EXISTS` 遇到已存在的表会静默跳过，写错了也不报错）。
#    要补，就从线上 dump 真实结构（information_schema.columns）再落成迁移文件。
KNOWN_MISSING = {
    "backtest_results": "routes/backtest.py：回测结果快照",
    "daily_predictions": "market_prediction.py：每日大盘推衍缓存",
    "opportunity_cache": "opportunity_service.py：早盘/尾盘机会缓存",
    "stock_analysis_cache": "routes/analysis.py：个股分析结果缓存",
    "trade_calendar": "trade_calendar_service.py：交易日历（V5.8 引入）",
    "user_holdings": "portfolio_service.py：用户持仓",
    "user_profiles": "portfolio_service.py / sim_service.py：用户档案与资金",
    "user_watchlist": "watchlist_service.py：自选股",
}


def _strip_sql_comments(src: str) -> str:
    """去掉 SQL 注释再匹配。

    必须做：说明性注释里会写「`CREATE TABLE IF NOT EXISTS`（会静默跳过）」这类句子，
    不去注释就会把注释里的示例当成真实 DDL（正则会捕到 `IF` 这种假表名）。
    """
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return "\n".join(re.sub(r"--.*$", "", line) for line in src.splitlines())


def _chain_files() -> list[pathlib.Path]:
    """真正会被自动迁移执行的文件集：v1 基础文件 + 所有 vN。"""
    files: list[pathlib.Path] = []
    base = BACKEND_DIR / BASE_SCHEMA
    if base.exists():
        files.append(base)
    return files + sorted(BACKEND_DIR.glob(MIGRATION_GLOB))


def _tables_in(path: pathlib.Path) -> set[str]:
    src = _strip_sql_comments(path.read_text(encoding="utf-8", errors="ignore"))
    return {
        m.group(1).lower()
        for m in re.finditer(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?([A-Za-z_]\w*)", src, re.I
        )
    }


def _referenced_tables() -> dict[str, set[str]]:
    """代码里通过 ``.table("x")`` 引用的表 → 引用它的文件集合。

    只认字面量。用变量传表名的（如 `_COOLDOWN_TABLE = "market_source_state"`）抓不到 ——
    漏抓只会让本测试少管一张表，不会误报，因此可以接受。
    """
    found: dict[str, set[str]] = {}
    for path in APP_DIR.rglob("*.py"):
        src = path.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"""\.table\(\s*["']([^"']+)["']""", src):
            found.setdefault(m.group(1).strip().lower(), set()).add(
                str(path.relative_to(BACKEND_DIR))
            )
    return found


def _created_tables() -> dict[str, set[str]]:
    """迁移链里建表的表名 → 出现在哪些文件。"""
    found: dict[str, set[str]] = {}
    for path in _chain_files():
        for table in _tables_in(path):
            found.setdefault(table, set()).add(path.name)
    return found


def _expected_tables() -> set[str]:
    """`/migrate/status` 的自检清单（延迟导入，避免测试收集期就去加载 app 包）。"""
    from app.routes.admin import EXPECTED_TABLES

    return {t.strip().lower() for t in EXPECTED_TABLES}


class SchemaCoverageTests(unittest.TestCase):
    def test_referenced_tables_all_have_create_sql(self) -> None:
        refs = _referenced_tables()
        created = _created_tables()
        self.assertGreater(len(refs), 15, "引用集合过小说明扫描本身坏了，不是「全都覆盖了」")
        self.assertGreater(len(created), 10, "建表集合过小说明扫描本身坏了")

        missing = sorted(t for t in refs if t not in created)
        unexpected = [t for t in missing if t not in KNOWN_MISSING]
        self.assertEqual(
            unexpected,
            [],
            "这些表被代码引用却在迁移链里找不到建表 SQL（新增技术债）：%s "
            "—— 要么补迁移文件，要么明确登记进 KNOWN_MISSING" % unexpected,
        )

    def test_known_missing_list_stays_honest(self) -> None:
        """清单里已补上 SQL 的表必须从清单移除，否则它就从「欠债登记」退化成「假台账」。"""
        created = _created_tables()
        fixed = sorted(t for t in KNOWN_MISSING if t in created)
        self.assertEqual(fixed, [], "这些表已有建表 SQL，请从 KNOWN_MISSING 移除：%s" % fixed)

    def test_confidence_slot_tables_are_now_covered(self) -> None:
        """本次补齐的两张表必须真的在迁移链里 —— 防止有人回退掉 v11。"""
        created = _created_tables()
        for table in ("quad_snapshots", "daily_recommend_snapshots"):
            self.assertIn(table, created, "%s 的建表 SQL 丢了" % table)


class MigrationChainTests(unittest.TestCase):
    def test_migration_files_follow_the_naming_the_runner_globs(self) -> None:
        # 自动迁移按 glob 排序执行，命名对不上就永远不会被跑到（静默失效）
        names = [p.name for p in _chain_files()]
        self.assertIn(BASE_SCHEMA, names)
        self.assertIn("supabase-schema-v11.sql", names)
        for name in names:
            if name != BASE_SCHEMA:
                self.assertRegex(name, r"^supabase-schema-v\d+\.sql$")

    def test_merged_legacy_file_is_not_part_of_the_chain(self) -> None:
        """`-all.sql` 不在自动迁移 glob 里，且不得成为某张表的唯一出处。

        若它独有某张表，说明那张表实际只存在于一个「不执行、且会与拆分版本漂移」的副本里，
        等于用影子文件定义生产结构 —— 必须提升为正式迁移。
        """
        merged = BACKEND_DIR / MERGED_LEGACY
        self.assertTrue(merged.exists(), "手工合并副本消失了？确认是有意删除再改本测试")
        self.assertNotIn(merged.name, [p.name for p in _chain_files()])
        self.assertNotRegex(merged.name, r"^supabase-schema-v\d+\.sql$")

        chain_tables = _created_tables()
        merged_only = sorted(t for t in _tables_in(merged) if t not in chain_tables)
        self.assertEqual(
            merged_only,
            [],
            "这些表只定义在 %s（不参与自动迁移）里，应移入正式迁移文件：%s"
            % (MERGED_LEGACY, merged_only),
        )


class SchemaIdempotencyTests(unittest.TestCase):
    """迁移文件必须幂等：可重复执行、不因重名而失败。"""

    def test_create_statements_use_if_not_exists(self) -> None:
        offenders = []
        for path in _chain_files():
            src = _strip_sql_comments(path.read_text(encoding="utf-8", errors="ignore"))
            for m in re.finditer(
                r"CREATE\s+(TABLE|INDEX|UNIQUE\s+INDEX)\s+(?!IF\s+NOT\s+EXISTS)(\w+)",
                src,
                re.I,
            ):
                offenders.append("%s: CREATE %s %s" % (path.name, m.group(1).upper(), m.group(2)))
        self.assertEqual(offenders, [], "非幂等 DDL（重跑会失败）：%s" % offenders)

    def test_create_policy_is_paired_with_drop_policy(self) -> None:
        offenders = []
        for path in _chain_files():
            src = _strip_sql_comments(path.read_text(encoding="utf-8", errors="ignore"))
            created = set(re.findall(r"CREATE\s+POLICY\s+\"?([\w]+)\"?", src, re.I))
            dropped = set(re.findall(r"DROP\s+POLICY\s+IF\s+EXISTS\s+\"?([\w]+)\"?", src, re.I))
            for name in sorted(created - dropped):
                offenders.append("%s: POLICY %s" % (path.name, name))
        self.assertEqual(
            offenders,
            [],
            "CREATE POLICY 缺配对的 DROP POLICY IF EXISTS（重跑会重名失败）：%s" % offenders,
        )


class AdminExpectedTablesTests(unittest.TestCase):
    """`/api/admin/migrate/status` 的自检清单必须与代码实际引用的表一致。

    修复背景（2026-09-20）：该清单原先写着 `portfolio_holdings` / `watchlist`，两个
    **既没有建表 SQL、也没有任何代码引用**的历史表名（真实表名是 `user_holdings` /
    `user_watchlist`）。后果不是「多检查了两张」那么轻：自检会**永远**把这两张报成
    missing、`all_ok` 永远 false，而它又恰恰没检查真正在用的持仓/自选表 ——
    一个只会喊狼来了的自检，比没有自检更糟（没人会再点开看）。
    """

    # 表名经变量传入、字面量扫描抓不到的。这不是「漏检」，是扫描方式的边界，
    # 因此显式登记而不是把清单改错去迁就扫描。
    VIA_VARIABLE = {
        "market_source_state": "routes/market.py:30 的 _COOLDOWN_TABLE",
    }

    def test_no_stale_table_names(self) -> None:
        literals = set(_referenced_tables())
        stale = sorted(
            t
            for t in _expected_tables()
            if t not in literals and t not in self.VIA_VARIABLE
        )
        self.assertEqual(
            stale,
            [],
            "这些表写进了 /migrate/status 的 EXPECTED_TABLES，但代码从不引用它们 "
            "→ 自检会一直报假缺失：%s" % stale,
        )

    def test_every_referenced_table_is_checked(self) -> None:
        literals = set(_referenced_tables())
        unchecked = sorted(literals - _expected_tables())
        self.assertEqual(
            unchecked,
            [],
            "代码在用、却没进 EXPECTED_TABLES 的表（等于没被自检）：%s" % unchecked,
        )

    def test_scan_and_list_are_both_non_trivial(self) -> None:
        """两边都太小说明扫描或清单本身坏了，而不是「恰好一致」。"""
        self.assertGreater(len(_referenced_tables()), 15)
        self.assertGreater(len(_expected_tables()), 15)


if __name__ == "__main__":
    unittest.main()
