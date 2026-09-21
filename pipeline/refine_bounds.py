"""按实际音量把句子的起止点挪到真正的停顿处。

为什么要这一步（见 docs/lessons.md 2026-09-21 那条）：识别给的时间点 40 毫秒一格，
而且句子起点系统性偏晚。直接用它，跳到一句开头会切掉第一个字的音头，
播到句末又容易带进下一句开头的一点声音。

做法：把音频切成 10 毫秒一帧算音量。句末只在识别给的句末前后 0.15 秒里找安静段，
放在安静段开始后一点点；句首只在识别给的句首前后 0.15 秒里找，放在安静段结束前一点点。
找不到安静段就保持识别给的时间；两句贴得太紧、挪完交叉了，就切在两者中间。

输入输出都是 lessons/<课>/timeline.json（原地改 start / end），并写一份报告。
在流程里排在 align.py 之后、teach.py 之前。
"""

import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio import to_mono_16k_wav  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FRAME = 0.01        # 每帧 10 毫秒
SEARCH = 0.15       # 在识别给的时间点前后各找这么远
QUIET_DB = 25       # 比说话时的典型音量低这么多分贝，算安静
TAIL = 0.04         # 句末在安静段开始后再留一点，别把尾音切掉
PREROLL = 0.05      # 句首在安静段结束前提前一点，别把音头切掉
MIN_QUIET = 0.03    # 安静段至少这么长才算数


def loudness(wav_path: Path) -> np.ndarray:
    """返回每 10 毫秒一帧的音量（分贝）。"""
    with wave.open(str(wav_path), "rb") as w:
        rate = w.getframerate()
        samples = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    x = samples.astype(np.float32) / 32768
    hop = int(rate * FRAME)
    n = len(x) // hop
    rms = np.sqrt(np.mean(x[: n * hop].reshape(n, hop) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    return np.convolve(db, np.ones(3) / 3, mode="same")  # 抹掉单帧的毛刺


def quiet_runs(db: np.ndarray, lo: int, hi: int, threshold: float) -> list[tuple[int, int]]:
    """[lo, hi) 里所有连续安静的帧段。"""
    runs, start = [], None
    for k in range(lo, hi):
        if db[k] < threshold:
            start = k if start is None else start
        elif start is not None:
            runs.append((start, k))
            start = None
    if start is not None:
        runs.append((start, hi))
    return [r for r in runs if (r[1] - r[0]) * FRAME >= MIN_QUIET]


def refine(sentences: list[dict], db: np.ndarray) -> dict:
    """句末只在原句末附近找，句首只在原句首附近找，各自最多挪 SEARCH 秒。

    不能在两句之间的整段空隙里找：片头之后有 5 秒多的音乐，整段找会把第 1 句的开头
    挪到音乐前面，点第 1 句就先放 5 秒音乐（2026-09-21 踩过）。
    """
    speech = float(np.percentile(db, 90))
    threshold = speech - QUIET_DB
    frames = len(db)
    to_frame = lambda t: max(0, min(frames, int(round(t / FRAME))))  # noqa: E731

    stats = {"boundaries": 0, "end_found": 0, "start_found": 0,
             "start_shift": [], "end_shift": []}
    for a, b in zip(sentences, sentences[1:]):
        stats["boundaries"] += 1
        middle = (a["end"] + b["start"]) / 2
        old_end, old_start = a["end"], b["start"]

        # 句末：安静段的开头，离原句末最近的那一段
        runs = quiet_runs(db, to_frame(max(a["start"] + 0.1, old_end - SEARCH)),
                          to_frame(min(old_end + SEARCH, max(middle, old_end))), threshold)
        if runs:
            q0 = min(runs, key=lambda r: abs(r[0] * FRAME - old_end))[0]
            a["end"] = round(q0 * FRAME + TAIL, 2)
            stats["end_found"] += 1

        # 句首：安静段的结尾，离原句首最近的那一段
        runs = quiet_runs(db, to_frame(max(old_start - SEARCH, min(middle, old_start))),
                          to_frame(min(b["end"] - 0.1, old_start + SEARCH)), threshold)
        if runs:
            q1 = min(runs, key=lambda r: abs(r[1] * FRAME - old_start))[1]
            b["start"] = round(q1 * FRAME - PREROLL, 2)
            stats["start_found"] += 1

        if a["end"] > b["start"]:  # 两句贴得太紧，切在中间
            a["end"] = b["start"] = round((a["end"] + b["start"]) / 2, 2)
        stats["end_shift"].append(a["end"] - old_end)
        stats["start_shift"].append(b["start"] - old_start)
    return stats


def build(lesson: str) -> None:
    lesson_dir = ROOT / "lessons" / lesson
    wav = lesson_dir / "audio_16k.wav"
    if not wav.exists():
        to_mono_16k_wav(next((ROOT / "materials" / lesson).glob("*.mp3")), wav)
    timeline_path = lesson_dir / "timeline.json"
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    stats = refine(timeline["sentences"], loudness(wav))
    timeline_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")

    ms = lambda v: f"{np.median(v) * 1000:+.0f}"  # noqa: E731
    lines = [
        f"# 句子边界精修报告 · {lesson}", "",
        f"- 相邻句交界 {stats['boundaries']} 处：句末找到安静段的 {stats['end_found']} 处，"
        f"句首找到安静段的 {stats['start_found']} 处，其余保持识别给的时间",
        f"- 句首平均挪动 {ms(stats['start_shift'])} 毫秒（负数是往前挪，说明识别给的起点偏晚）",
        f"- 句末平均挪动 {ms(stats['end_shift'])} 毫秒",
        f"- 挪得最远的：句首 {max(abs(v) for v in stats['start_shift']) * 1000:.0f} 毫秒，"
        f"句末 {max(abs(v) for v in stats['end_shift']) * 1000:.0f} 毫秒（设计上限 {SEARCH * 1000:.0f} 毫秒加一点余量）",
    ]
    (lesson_dir / "bounds_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[2:]))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    build(sys.argv[1] if len(sys.argv) > 1 else "260821")
