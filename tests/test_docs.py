"""文档和代码对不对得上。

为什么要有（2026-09-23 拆规格时加的）：《AI 编程项目管理指南》第六章——描述「代码现在长什么样」的话，
要么配会报错的检查，要么别写。docs/architecture.md 和 specs/ 里写着文件、字段、验收编号，代码一改就可能过期，没人发现。

查四样：
1. 文档里用反引号写到的仓库路径都在。<课> 换成第一集 260821；被 .gitignore 挡住的（随时能重新生成的、密钥文件）不查。
   只查描述「现在」的文档；交接页、教训、决策是历史记录，里面写到删掉的文件是正常的，不查。
2. pipeline/、web/、tests/ 下的代码文件，docs/architecture.md 里都写到了。
3. tests/test_player.py 的每个自动检查（用例名开头的 A 编号）都在某份规格里写着；
   规格里的 A 编号，没标「（人工）」的，测试里都有。
4. docs/architecture.md「课程文件」那张表里的字段，第一集的 lesson.json 里都有。

跑法：<pywork python> tests/test_docs.py   （不到 1 秒，不连网）
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LESSON = "260821"
CURRENT_DOCS = ["CLAUDE.md", "demand.md", "docs/architecture.md", "docs/workflow.md", "docs/environment.md", "docs/debts.md",
                *sorted(str(p.relative_to(ROOT)).replace("\\", "/") for p in (ROOT / "specs").glob("*.md"))]
PATH_ROOTS = ("pipeline/", "web/", "tests/", "docs/", "specs/", "lessons/", "materials/", ".claude/")
TOP_FILES = {"demand.md", "CLAUDE.md", "idea.txt", "start-player.bat", "api-keys.txt"}
ID = re.compile(r"(?<![0-9A-Za-z-])(A(?:\d+[a-z]*\d*|-next|-prev))(?![0-9A-Za-z])")

failures: list[str] = []
passes: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (passes if ok else failures).append(name)
    print(f"  {'通过' if ok else '未通过'}　{name}" + (f"　{detail}" if detail else ""))


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def ignored(rel: str) -> bool:
    return subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT).returncode == 0


def paths_in(text: str) -> set[str]:
    out = set()
    for token in re.findall(r"`([^`\n]+)`", text):
        rel = token.split()[0].replace("<课>", LESSON)
        if "<" in rel or "*" in rel:
            continue
        if rel.startswith(PATH_ROOTS) or rel in TOP_FILES:
            out.add(rel)
    return out


def has(obj, parts: list[str]) -> bool:
    """字段在不在：a.b 是字典里的键，a[] 是列表（有一个元素有就算），* 是字典里任意一个值。"""
    if not parts:
        return True
    head, rest = parts[0], parts[1:]
    if head == "*":
        return isinstance(obj, dict) and any(has(v, rest) for v in obj.values())
    if head.endswith("[]"):
        items = obj.get(head[:-2]) if isinstance(obj, dict) else None
        return isinstance(items, list) and any(has(v, rest) for v in items)
    return isinstance(obj, dict) and head in obj and has(obj[head], rest)


def main() -> None:
    print("\n【文档里写到的文件都在】")
    for doc in CURRENT_DOCS:
        missing = sorted(p for p in paths_in(read(doc)) if not (ROOT / p).exists() and not ignored(p))
        check(f"D1 {doc} 里写到的路径都在", not missing, "、".join(missing))

    print("\n【代码文件都写进了架构文档】")
    arch = read("docs/architecture.md")
    code = sorted(str(p.relative_to(ROOT)).replace("\\", "/")
                  for pattern in ("pipeline/*.py", "pipeline/*.html", "web/*.html", "web/*.js", "web/*.css", "tests/*.py")
                  for p in ROOT.glob(pattern))
    absent = [c for c in code if c not in arch]
    check("D2 pipeline/、web/、tests/ 下每个文件 docs/architecture.md 都写到了", not absent, "、".join(absent))

    print("\n【自动检查的编号和规格对得上】")
    tests = set(re.findall(r'check\(\s*"(A[0-9A-Za-z-]+)', read("tests/test_player.py")))
    spec_text = "\n".join(read(f"specs/{p.name}") for p in sorted((ROOT / "specs").glob("SPEC-[0-9]*.md")))
    in_specs, manual = set(), set()
    for m in ID.finditer(spec_text):
        (manual if spec_text.startswith("（人工）", m.end()) else in_specs).add(m.group(1))
    undocumented = sorted(tests - in_specs - manual)
    check("D3 每个自动检查都在某份规格里写着", not undocumented, "、".join(undocumented))
    untested = sorted(in_specs - tests)
    check("D4 规格里没标人工的验收编号，测试里都有", not untested, "、".join(untested))

    print("\n【课程文件的字段都在】")
    section = re.search(r"## 课程文件.*?\n(.*?)(?=\n## )", arch, re.S)
    fields = [f for row in (section.group(1) if section else "").splitlines() if row.startswith("| `")
              for f in re.findall(r"`([^`]+)`", row.split("|")[1])]
    lesson = json.loads(read(f"lessons/{LESSON}/lesson.json"))
    gone = [f for f in fields if not has(lesson, f.split("."))]
    check("D5 docs/architecture.md 列的 lesson.json 字段第一集都有", bool(fields) and not gone,
          f"列了 {len(fields)} 个" + (f"，没有的：{'、'.join(gone)}" if gone else ""))

    print(f"\n通过 {len(passes)} 项，未通过 {len(failures)} 项")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
