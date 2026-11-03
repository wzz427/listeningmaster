"""金样考卷：切割引擎（pipeline/slicing）改代码必过（SPEC-012 R1–R7，owner 2026-11-03 拍板）。

为什么要有：改边界代码以前只能靠人耳抽查才知道退没退步；现在四课的 timeline 就是标准答案，
重放一遍逐句对，退步当场红。金样另有三处人工标准答案：第一集 7 句疑难归因（SPEC-004 的表）、
4 条人耳确认（lessons/260821/bounds_manual.json）、250123 结尾预告的说话人（lessons/250123/speaker_manual.json）。

离线：识别吃 asr_raw.json、机器耳朵吃 ear_cache.json，全程不联网不花钱（换 STEP、MAX_MOVE 这类
会改试探点阵的参数做实验时，删对应课的 ear_cache.json 重听——SPEC-012 R7）。

查五样：
A1 四课用一条命令（run.run）在临时目录重放，timeline 和金样逐句完全一致——搬家不改结果（R1）、
   一条命令跑完整条链（R2）。
A2 对上率四课都 ≥ 80%（R3 红线；低于先怀疑讲稿和录音不是同一版）。
A3 重放出的 engine 版本 ＝ version.py 的 ENGINE_VERSION，四课金样里写的也是它（R4）。
A4 第一集 4 条人耳确认：重放的起止 ＝ bounds_manual.json 的值（R5，人耳盖过机器）。
A5 考卷真咬人：把机器耳朵的句末余量 PAD 故意改坏重放第一集，必须和金样不一样——一样说明这份
   考卷是橡皮图章，本身就不过（R6）。只动 PAD 这类不改试探点阵的参数；考卷把耳朵换成了「一联网
   就报错」的哨兵，谁改出缓存没有的片段谁当场红（R7）。

跑法：<pywork python> tests/test_slicing.py   （约半分钟，不联网）
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline" / "slicing"))
import ear_bounds  # noqa: E402
import run as engine  # noqa: E402  —— 名字太通用，用 engine 称呼
import version  # noqa: E402


def _no_network(path, tries=6):
    raise RuntimeError("考卷不联网：机器耳朵缓存里没有这个片段——改了会改试探点阵的参数？"
                       "删对应课的 ear_cache.json 重听（SPEC-012 R7）")


ear_bounds.hear = _no_network   # 考卷只吃缓存，想联网就大声失败，绝不悄悄花钱

LESSONS = ["260821", "250918", "261009", "250123"]
MANUAL_LESSON = "260821"   # bounds_manual.json 只第一集有（SPEC-004 R5）

failures: list[str] = []
passes: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (passes if ok else failures).append(name)
    print(f"  {'通过' if ok else '未通过'}　{name}" + (f"　{detail}" if detail else ""))


def replay(lesson: str):
    """把一课的输入搬进临时目录，用引擎一条命令重放；返回（重放出的 timeline，质量统计）。不碰正式课目录。"""
    tmp = Path(tempfile.mkdtemp())
    lesson_dir = tmp / "lessons" / lesson
    material_dir = tmp / "materials" / lesson
    lesson_dir.mkdir(parents=True)
    material_dir.mkdir(parents=True)
    for f in (ROOT / "materials" / lesson).iterdir():
        if f.suffix in (".mp3", ".pdf", ".txt"):
            shutil.copy2(f, material_dir / f.name)
    for name in ("asr_raw.json", "ear_cache.json", "audio.m4a", "audio_16k.wav",
                 "bounds_manual.json", "speaker_manual.json"):
        src = ROOT / "lessons" / lesson / name
        if src.exists():
            shutil.copy2(src, lesson_dir / name)
    try:
        stats = engine.run(lesson, root=tmp)
        timeline = json.loads((lesson_dir / "timeline.json").read_text(encoding="utf-8"))
        return timeline, stats
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def golden(lesson: str) -> dict:
    return json.loads((ROOT / "lessons" / lesson / "timeline.json").read_text(encoding="utf-8"))


def main() -> None:
    print("\n【A1/A2/A3/A4 四课重放对金样】（离线，吃 asr_raw 和耳朵缓存）")
    replays: dict[str, tuple[dict, dict]] = {}
    for lesson in LESSONS:
        timeline, stats = replay(lesson)
        replays[lesson] = (timeline, stats)
        gold = golden(lesson)
        strip_engine = lambda d: {k: v for k, v in d.items() if k != "engine"}  # noqa: E731 版本字段归 A3 专管
        check(f"A1 {lesson} 一条命令重放＝金样，逐句完全一致", strip_engine(timeline) == strip_engine(gold))
        check(f"A2 {lesson} 对上率 ≥ 80%", stats["align"]["match_rate"] >= 0.80,
              f"{stats['align']['matched']}/{stats['align']['script_words']}（{stats['align']['match_rate']:.0%}）")
        check(f"A3 {lesson} engine 版本＝version.py", timeline.get("engine") == version.ENGINE_VERSION
              and gold.get("engine") == version.ENGINE_VERSION, timeline.get("engine", ""))

    manual = json.loads((ROOT / "lessons" / MANUAL_LESSON / "bounds_manual.json").read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in replays[MANUAL_LESSON][0]["sentences"]}
    bad = [f"第{sid}句{side}" for sid, fix in manual["sentences"].items()
           for side in ("start", "end") if side in fix and by_id[int(sid)][side] != fix[side]]
    check(f"A4 第一集 {len(manual['sentences'])} 条人耳确认全部生效（起止＝bounds_manual.json）",
          not bad, "、".join(bad))

    print("\n【A5 考卷真咬人】把机器耳朵的句末余量 PAD 从 0.03 改成 0.10，重放第一集必须和金样不一样")
    saved = ear_bounds.PAD
    try:
        ear_bounds.PAD = 0.10   # 只改本地计算、不改听哪些片段（考卷才离线得起来，SPEC-012 R6）
        sabotaged, _ = replay(MANUAL_LESSON)
        check("A5 改坏参数后重放 ≠ 金样（考卷能查出退步）", sabotaged != golden(MANUAL_LESSON))
    finally:
        ear_bounds.PAD = saved

    print(f"\n通过 {len(passes)} 项，未通过 {len(failures)} 项")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
