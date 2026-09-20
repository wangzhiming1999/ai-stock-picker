"""用例收集守卫：防止用例文件「存在，但一条都不跑」。

背景（2026-09-20 技术债清理时发现）：
pytest 默认只收集 `Test*` 命名的类；`unittest.TestCase` 子类不受该限制、**普通类却受**。
而本仓库的命名约定是 `*Tests` —— 于是同样写 `*Tests` 的类，继承 TestCase 的能被收集、
不继承的静默收集 0 条，没有任何提示。长期失效的用例共 **20 条**：

- `test_limitup_snapshot_store.py` 7 条（涨停池落库 / 累积表回补 / 静默降级）
- `test_sim_relay_auto_buy.py` 13 条（含连板接力「一字板买不进」判据 `_relay_unfillable`）

`python_classes` 已在 pytest.ini 显式声明为 `Test* *Tests`。本文件守住两件事：
配置别再被删掉，以及新增用例文件不得写成「收集不到的类」。
"""

import fnmatch
import pathlib
import re
import unittest

TESTS_DIR = pathlib.Path(__file__).resolve().parent
BACKEND_DIR = TESTS_DIR.parent
PYTEST_INI = BACKEND_DIR / "pytest.ini"


def _collectible_class_names() -> tuple[str, ...]:
    """从 pytest.ini 读 python_classes（缺省时返回 pytest 的默认约定）。"""
    if not PYTEST_INI.exists():
        return ("Test",)
    for line in PYTEST_INI.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("python_classes"):
            _, _, value = line.partition("=")
            return tuple(value.split())
    return ("Test",)


def _test_method_names(body: str) -> list[str]:
    # 用 [ \t] 而不是 \s：`\s` 也吃换行，会把紧跟在类体后面的**模块级**函数算进类里
    return re.findall(r"^[ \t]+(?:async[ \t]+)?def[ \t]+(test\w*)[ \t]*\(", body, re.M)


def _class_bodies(src: str) -> list[tuple[str, str, str]]:
    """[(类名, 基类串, 类体)]，按出现顺序。"""
    out: list[tuple[str, str, str]] = []
    matches = list(re.finditer(r"^class\s+(\w+)\s*(?:\(([^)]*)\))?\s*:", src, re.M))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(src)
        out.append((m.group(1), m.group(2) or "", src[start:end]))
    return out


def _matches_any(name: str, patterns: tuple[str, ...]) -> bool:
    """pytest 的 python_classes 语义：无通配符的条目按**前缀**匹配，有通配符的按 glob。"""
    for pattern in patterns:
        glob = pattern if "*" in pattern else pattern + "*"
        if fnmatch.fnmatchcase(name, glob):
            return True
    return False


class PytestCollectionGuardTests(unittest.TestCase):
    def test_python_classes_covers_the_repo_naming_convention(self) -> None:
        declared = _collectible_class_names()
        self.assertTrue(
            _matches_any("SnapshotRowTests", declared),
            "pytest.ini 的 python_classes 收不到 `*Tests` 命名的普通类 —— "
            "这类用例会静默 0 条，且不会报错。当前声明：%s" % (declared,),
        )
        # unittest.TestCase 子类不受 python_classes 限制，但普通类（Test* 前缀）也要能收
        self.assertTrue(_matches_any("TestFoo", (declared[0], *declared)))

    def test_no_test_class_can_be_silently_skipped(self) -> None:
        declared = _collectible_class_names()
        offenders = []
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            src = path.read_text(encoding="utf-8", errors="ignore")
            for name, bases, body in _class_bodies(src):
                if "TestCase" in bases:
                    continue  # unittest 子类总能被收集，与类名无关
                if not _test_method_names(body):
                    continue  # 纯 helper 类（_FakeSB 之类）不参与
                if not _matches_any(name, declared):
                    offenders.append(
                        "%s::%s（%d 条用例收不到）" % (path.name, name, len(_test_method_names(body)))
                    )
        self.assertEqual(
            offenders,
            [],
            "这些类里的用例永远不会被执行（类名不在 python_classes 内，且没继承 TestCase）：%s"
            % offenders,
        )

    def test_every_test_file_has_at_least_one_case(self) -> None:
        empty = []
        for path in sorted(TESTS_DIR.glob("test_*.py")):
            src = path.read_text(encoding="utf-8", errors="ignore")
            has_module_level = bool(
                re.search(r"^(?:async[ \t]+)?def[ \t]+test\w*[ \t]*\(", src, re.M)
            )
            has_in_class = any(_test_method_names(b) for _, _, b in _class_bodies(src))
            if not (has_module_level or has_in_class):
                empty.append(path.name)
        self.assertEqual(empty, [], "这些文件没有任何用例：%s" % empty)


if __name__ == "__main__":
    unittest.main()
