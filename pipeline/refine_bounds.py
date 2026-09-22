"""按实际音量把句子的起止点挪到真正的停顿处。

为什么要这一步（见 docs/lessons.md 2026-09-21 那条）：识别给的时间点 40 毫秒一格，
而且句子起点系统性偏晚。直接用它，跳到一句开头会切掉第一个字的音头，
播到句末又容易带进下一句开头的一点声音。

做法：把音频切成 10 毫秒一帧算音量。句末只在识别给的句末前后 0.15 秒里找安静段，
放在安静段开始后一点点；句首只在识别给的句首前后 0.15 秒里找，放在安静段结束前一点点。
找不到安静段就保持识别给的时间；两句贴得太紧、挪完交叉了，就切在两者中间。

词也一样挪：词和词之间的切口挪到附近最安静的一帧，并定好点每个词时播哪一段原声（见 refine_words）。

输入输出都是 lessons/<课>/timeline.json（原地改 start / end），并写一份报告。
在流程里排在 align.py 之后、teach.py 之前。加 --words-only 只重做词、句子不动。
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
WORD_SEARCH = 0.15  # 词和词之间的切口，在识别给的时间前后找这么远
WORD_QUIET = 20     # 切口比说话时的典型音量低这么多分贝，才算切得开
CLIP_WORDS = 4      # 连读的一小串最多这么多个词，再长就不单独给原声
CLIP_SECONDS = 1.8  # 也最长这么多秒


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


def refine_words(sentences: list[dict], db: np.ndarray) -> dict:
    """把词和词之间的切口挪到附近最安静的一帧，再给每个词定好「点它时播哪一段原声」（clip）。

    识别给的词边界常偏 0.1 秒左右，播放器原来还在前后各多放 0.06 秒，
    结果单播一个词会带进前后词的碎片（2026-09-22 owner 听出来的）。量下来正文 732 个词里，
    只有 3% 两头都切在安静处。
    连读的词中间根本没有空隙，挪到哪都切不开（I've finished）。这种就把连着读的那一小串一起播，
    两头照样切在空隙处：没有碎片，孩子还能听到连读本身，这正是他听不出来的地方。
    连得太长（超过 CLIP_WORDS 个词或 CLIP_SECONDS 秒）就不给，让他听整句。
    clip 是 [这一串第一个词, 最后一个词] 在本句里的序号；给不了就是 null。
    识别给的原始时间存在 asr 字段里，重跑总是从它出发，不会越挪越远。
    """
    speech = float(np.percentile(db, 90))
    frames = len(db)
    to_frame = lambda t: max(0, min(frames - 1, int(round(t / FRAME))))  # noqa: E731

    def quietest(t0: float, t1: float) -> int:
        lo = to_frame(t0)
        return min(range(lo, max(lo, to_frame(t1)) + 1), key=lambda i: db[i])

    stats = {"words": 0, "single": 0, "linked": 0, "none": 0}
    for s in sentences:
        words = s["words"]
        n = len(words)
        if not n:
            continue
        for w in words:
            w.setdefault("asr", [w["start"], w["end"]])
            w.pop("clean", None)  # 2026-09-22 头一版的标记，已由 clip 取代
        asr = [w["asr"] for w in words]
        middle = [(a + b) / 2 for a, b in asr]
        # 第 j 个切口在第 j-1 个词和第 j 个词之间。识别给的时间偏晚，所以往前找得远、往后找得近
        cuts = []
        for j in range(n + 1):
            if j == 0:
                a, b = asr[0]
                lo, hi = max(s["start"] - 0.1, a - WORD_SEARCH), a + min(0.06, (b - a) / 4)
            elif j == n:
                a, b = asr[-1]
                lo, hi = b - min(WORD_SEARCH, (b - a) / 2), min(s["end"] + 0.1, b + 0.12)
            else:
                (pa, pb), (a, b) = asr[j - 1], asr[j]
                lo = max(middle[j - 1], pb - min(WORD_SEARCH, (pb - pa) / 2))
                hi = min(middle[j], a + min(0.06, (b - a) / 4))
            cuts.append(quietest(lo, hi))
        quiet = [bool(db[c] - speech <= -WORD_QUIET) for c in cuts]
        for k in range(n):
            words[k]["start"], words[k]["end"] = round(cuts[k] * FRAME, 2), round(cuts[k + 1] * FRAME, 2)
            # 被挤得不到识别时长一半的词，多半是切进了词里面：两头都当作切不开
            if (cuts[k + 1] - cuts[k]) * FRAME < 0.5 * (asr[k][1] - asr[k][0]):
                quiet[k] = quiet[k + 1] = False
        for k in range(n):
            first, last = k, k
            while not quiet[first] and first > 0:
                first -= 1
            while not quiet[last + 1] and last + 1 < n:
                last += 1
            seconds = (cuts[last + 1] - cuts[first]) * FRAME
            ok = quiet[first] and quiet[last + 1] and last - first + 1 <= CLIP_WORDS and seconds <= CLIP_SECONDS
            words[k]["clip"] = [first, last] if ok else None
            stats["words"] += 1
            stats["none" if not ok else "single" if first == last else "linked"] += 1
    return stats


def build(lesson: str, words_only: bool = False) -> None:
    lesson_dir = ROOT / "lessons" / lesson
    wav = lesson_dir / "audio_16k.wav"
    if not wav.exists():
        to_mono_16k_wav(next((ROOT / "materials" / lesson).glob("*.mp3")), wav)
    timeline_path = lesson_dir / "timeline.json"
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    db = loudness(wav)
    stats = None if words_only else refine(timeline["sentences"], db)
    word_stats = refine_words(timeline["sentences"], db)
    timeline_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")

    report = lesson_dir / "bounds_report.md"
    if stats is None:  # 只重做了词：保留原来那份句子的报告，只换掉词那一行
        old = report.read_text(encoding="utf-8").splitlines() if report.exists() else [f"# 边界精修报告 · {lesson}", ""]
        lines = [x for x in old if not x.startswith("- 词：")]
    else:
        ms = lambda v: f"{np.median(v) * 1000:+.0f}"  # noqa: E731
        lines = [
            f"# 边界精修报告 · {lesson}", "",
            f"- 相邻句交界 {stats['boundaries']} 处：句末找到安静段的 {stats['end_found']} 处，"
            f"句首找到安静段的 {stats['start_found']} 处，其余保持识别给的时间",
            f"- 句首平均挪动 {ms(stats['start_shift'])} 毫秒（负数是往前挪，说明识别给的起点偏晚）",
            f"- 句末平均挪动 {ms(stats['end_shift'])} 毫秒",
            f"- 挪得最远的：句首 {max(abs(v) for v in stats['start_shift']) * 1000:.0f} 毫秒，"
            f"句末 {max(abs(v) for v in stats['end_shift']) * 1000:.0f} 毫秒（设计上限 {SEARCH * 1000:.0f} 毫秒加一点余量）",
        ]
    lines.append(f"- 词：共 {word_stats['words']} 个。点它能单独听原声的 {word_stats['single']} 个；"
                 f"和前后连读、播连着读的一小串的 {word_stats['linked']} 个；连得太长、不给原声的 {word_stats['none']} 个"
                 f"（切口要比说话声低 {WORD_QUIET} 分贝才算切得开）")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[2:]))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    build(args[0] if args else "260821", words_only="--words-only" in sys.argv)
