"""一条命令跑完切割整条链：mp3＋讲稿 → 逐句时间轴＋质量报告（SPEC-012）。

用法：<pywork python> pipeline/slicing/run.py <课> [--asr]
  --asr  强制重新识别（默认 lessons/<课>/asr_raw.json 已在就沿用，识别要花钱、原样留着）

链上的六道工序还是每步一个程序、落中间文件、能单独重跑（SPEC-002「决策依据」定的结构，
run.py 只管按顺序点名，不合并）：audio（m4a）→ asr_probe（识别，可跳）→ transcript＋align（对齐切句）
→ refine_bounds（按音量精修）→ ear_bounds（机器耳朵复查＋人耳层＋写版本戳）。
机器耳朵听过的片段吃 lessons/<课>/ear_cache.json，重放不联网不花钱。

出：lessons/<课>/timeline.json（带 engine 版本字段）、quality_report.md（四指标）。
退出码：0 成功；10 音频；20 识别；30 其他——serve.py 备课按这个码报人话。
"""

import json
import sys
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).resolve().parent))
import align  # noqa: E402
import asr_probe  # noqa: E402
import audio  # noqa: E402
import ear_bounds  # noqa: E402
import no_transcript  # noqa: E402
import refine_bounds  # noqa: E402
from version import ENGINE_VERSION  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent


def _has_script(lesson: str, root: Path) -> bool:
    """材料夹里有没有讲稿（判据和 align.build 认讲稿的写法一致）——有走对齐，没有走无讲稿路。"""
    mdir = root / "materials" / lesson
    return any(mdir.glob("*transcript.pdf")) or (mdir / "transcript.txt").exists()


class StageError(Exception):
    """哪一步没成：code 是退出码（10 音频、20 识别、30 其他），what 是那步的名字。"""

    def __init__(self, code: int, what: str, hint: str = ""):
        super().__init__(f"{what}这一步没成功" + (f"：{hint}" if hint else ""))
        self.code = code


def _do(code: int, what: str, fn):
    try:
        return fn()
    except SystemExit as e:            # align 没讲稿这类：提示本身就是人话，带出去
        raise StageError(code, what, str(e)) from e
    except Exception as e:             # 细节进不了人话（红线：不透内部），运维看 stderr 的异常链
        print(f"[{what}] {type(e).__name__}: {e}", file=sys.stderr)
        raise StageError(code, what) from e


def run(lesson: str, root: Path = ROOT, force_asr: bool = False) -> dict:
    """跑完整条链，返回质量统计（金样考卷 tests/test_slicing.py 也走这个入口）。"""
    lesson_dir = root / "lessons" / lesson
    lesson_dir.mkdir(parents=True, exist_ok=True)
    stats: dict = {"lesson": lesson, "engine": ENGINE_VERSION}

    _do(10, "音频", lambda: audio.build(lesson, root))
    if force_asr or not (lesson_dir / "asr_raw.json").exists():
        _do(20, "识别", lambda: asr_probe.build(lesson, root))
    else:
        print("识别结果已在（asr_raw.json），沿用不重识别；要重来加 --asr")
    if _has_script(lesson, root):
        stats["align"] = _do(30, "对齐", lambda: align.build(lesson, root))
    else:   # 没带讲稿：句子、文字、说话人全凭识别（SPEC-013）；出课的其余各步和带讲稿同一条链
        stats["align"] = _do(30, "对齐", lambda: no_transcript.build(lesson, root))
    stats["refine"] = _do(30, "精修", lambda: refine_bounds.build(lesson, root))
    stats["ear"] = _do(30, "机器耳朵", lambda: ear_bounds.main(lesson, root))
    write_report(lesson, root, stats)
    return stats


def write_report(lesson: str, root: Path, stats: dict) -> None:
    """质量报告（SPEC-012 四指标；无讲稿课换掉对上率那一行，SPEC-013 R8）。"""
    a, r, e = stats["align"], stats["refine"], stats["ear"]
    ms = lambda v: f"{median(v) * 1000:+.0f}"  # noqa: E731
    first_ok, last_ok = e["heard"] - e["first_missing"], e["heard"] - e["last_missing"]
    pct = lambda n: f"{n / e['heard']:.0%}" if e["heard"] else "—"  # noqa: E731
    if a.get("path") == "free":
        head = [
            f"# 切割质量报告 · {lesson}", "",
            f"引擎 {stats['engine']}（SPEC-012）。这一课没带讲稿，走的无讲稿路（SPEC-013）："
            "文字凭识别原样，没有对上率可看。", "",
            f"- **说话人**：{a['note'] or '—'}（识别分出 {a['speaker_ids']} 个编号，归并成 {a['speakers']} 位；"
            + ("其中判为片头/预告的句子照留，只是不进正文分段）" if a.get("outside") else "无片头/预告编号") + "）",
            "- **编号归并**：" + "、".join(f"{k}→{v}" for k, v in sorted(a["labels"].items())),
            f"- **巨词恢复**：识别挤成一团的 {a['mega_total']} 处——大模型加空格 {a['mega_llm']} 处、"
            f"词频兜底 {a['mega_dp']} 处、原样保留 {a['mega_kept']} 处",
            f"- **并半句**：{a['merged']} 处",
        ]
    else:
        head = [
            f"# 切割质量报告 · {lesson}", "",
            f"引擎 {stats['engine']}（SPEC-012）。低于线先查讲稿和录音是不是同一版，再查机器耳朵有没有被限流。", "",
            f"- **对上率**：{a['matched']}/{a['script_words']}（{a['match_rate']:.0%}）——红线 80%",
        ]
    lines = head + [
        f"- **首末词通过率**（机器耳朵）：正文 {e['heard']} 句，第一个词听到的 {first_ok}/{e['heard']}"
        f"（{pct(first_ok)}）、最后一个词听到的 {last_ok}/{e['heard']}（{pct(last_ok)}）",
        f"- **边界挪动**：精修句首中位 {ms(r['start_shift'])} 毫秒（最远 {max(abs(v) for v in r['start_shift']) * 1000:.0f}）、"
        f"句末中位 {ms(r['end_shift'])} 毫秒（最远 {max(abs(v) for v in r['end_shift']) * 1000:.0f}）——"
        f"超过 200 毫秒查精修搜索范围；机器耳朵另挪 {e['moved']} 处（上限 600 毫秒）",
        f"- **疑点句**（要人耳抽查）：机器挪到头也没听到的 {len(e['unfixed'])} 处、"
        f"照人耳确认改的 {len(e['manual'])} 处、照人定说话人改的 {len(e['speaker'])} 处",
        f"- 机器耳朵缓存：新听 {e['cache_fresh']} 段、现成 {e['cache_total'] - e['cache_fresh']} 段",
    ]
    for sid, side, text, got in e["unfixed"]:
        lines.append(f"  - 第 {sid} 句{side}「{text[:40]}{'…' if len(text) > 40 else ''}」，机器听到「{got[:40]}」")
    lines += ["", f"（这页是汇总；细账在 align_report.md、bounds_report.md、ear_report.md。）"]
    (root / "lessons" / lesson / "quality_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    try:
        result = run(args[0] if args else "260821", force_asr="--asr" in sys.argv)
    except StageError as err:
        print(err, file=sys.stderr)
        sys.exit(err.code)
    if result["align"].get("path") == "free":
        a = result["align"]
        print(f"完成：{result['engine']}，无讲稿路 {a['sentences']} 句、说话人 {a['speakers']} 位、"
              f"并半句 {a['merged']} 处，质量报告在 lessons/{result['lesson']}/quality_report.md")
    else:
        print(f"完成：{result['engine']}，正文 {result['align']['body']} 句，对上率 {result['align']['match_rate']:.0%}，"
              f"质量报告在 lessons/{result['lesson']}/quality_report.md")
