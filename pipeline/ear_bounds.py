"""用机器耳朵查每句的开头和结尾有没有被切掉；切掉了就往外挪，直到听得到。

为什么要这一步（2026-09-22）：按音量精修过的句子边界，机器耳朵把全集 89 句听了一遍，
仍有约 9 句的第一个词没了或只剩半截（Sugar、Goodbye、Neil、Yes、Hi 的 H……）。
原因是识别给的句首有时晚 0.3 秒，超出了 refine_bounds.py 的搜索范围；有的句首前面垫着片尾音乐，
按音量根本找不到「安静」。孩子按「重听本句」就听不到开头，这是核心功能的毛病。

做法：把每句按现在的起止从 16k 音频切出来，交给机器耳朵（pipeline/ear.py）听。
- 第一个词没听到：句首每次往前挪 0.04 秒再听，最多挪 0.6 秒，不越过上一句的结尾，找到离原句首最近的、听得到的位置。
- 机器耳朵很宽容，Sugar 只剩 -ugar 它也听成 Sugar，所以「听到了」不等于开头没切掉。
  每一句都再从这个位置按音量往前找到真正开口的地方：比附近最安静处高出 ONSET_DB 分贝以内算没出声
  （不用全局的「安静」标准，句首垫着片尾音乐时全局标准找不到安静），再往前留 PREROLL 秒。
- 最后一个词没听到：句末每次往后挪 0.04 秒再听，不越过下一句的开头，取最近的听得到的位置再往后留 0.03 秒。
- 挪到头也听不到的（多半是机器耳朵自己的毛病，比如 Itmeans、I've 听成 I），保持原样，写进报告给人耳查。

人耳说了算：lessons/<课>/bounds_manual.json 里是 owner 用耳朵确认过的起止点，最后照它改，盖过上面机器挪的结果。
机器耳朵也有听错的时候（第 76 句 Neil 明明在，它听不到），也有找不回来的（第 48 句，见那个文件里的说明）。
只改了 bounds_manual.json、不想重新调识别接口时：<pywork python> pipeline/ear_bounds.py <课> --manual

在流程里排在 refine_bounds.py 之后、teach.py 之前。原地改 lessons/<课>/timeline.json，报告写到 ear_report.md。
要调百炼识别接口，一集花一两毛钱。
"""

import json
import sys
import tempfile
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ear import hear, words_of  # noqa: E402
from refine_bounds import FRAME, PREROLL, loudness  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTSIDE = "片头片尾"
RATE = 16000
STEP = 0.04       # 每次挪这么多秒再听
MAX_MOVE = 0.6    # 最多挪这么远
PAD = 0.03        # 句末听到之后再往后留一点
ONSET_DB = 6      # 比附近最安静处高出这么多分贝以内，算还没开口
WORKERS = 4        # 同时发太多会被限流


def onset(db: np.ndarray, at: float, floor: float) -> float:
    """at 附近这一段声音真正开始的地方：at 还没出声就往后找，已经在出声就往前找
    （不早于 floor，最多往前 MAX_MOVE 秒）。"""
    lo, k = int(round(max(floor, at - MAX_MOVE) / FRAME)), int(round(at / FRAME))
    quiet = float(db[lo:k + 21].min()) + ONSET_DB
    if db[k] <= quiet:  # 还没出声：往后找第一帧出声的（最多 0.2 秒）
        ahead = np.flatnonzero(db[k:k + 21] > quiet)
        return (k + int(ahead[0])) * FRAME if len(ahead) else at
    while k > lo and db[k - 1] > quiet:
        k -= 1
    return k * FRAME


def apply_manual(lesson_dir: Path, sentences: list[dict]) -> list[str]:
    """照 bounds_manual.json 改人耳确认过的起止点，返回改了哪些（给报告用）。"""
    path = lesson_dir / "bounds_manual.json"
    if not path.exists():
        return []
    by_id = {s["id"]: s for s in sentences}
    done = []
    for sid, fix in json.loads(path.read_text(encoding="utf-8"))["sentences"].items():
        s = by_id[int(sid)]
        for side in ("start", "end"):
            if side in fix and s[side] != fix[side]:
                done.append(f"第 {sid} 句{'开头' if side == 'start' else '结尾'} {s[side]:.2f} → {fix[side]:.2f}")
                s[side] = fix[side]
    return done


def manual_only(lesson: str) -> None:
    lesson_dir = ROOT / "lessons" / lesson
    timeline_path = lesson_dir / "timeline.json"
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    done = apply_manual(lesson_dir, timeline["sentences"])
    timeline_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(done) if done else "人耳确认过的起止点都已经是这样了，没有要改的")


def main(lesson: str) -> None:
    lesson_dir = ROOT / "lessons" / lesson
    with wave.open(str(lesson_dir / "audio_16k.wav")) as w:
        ref = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    timeline_path = lesson_dir / "timeline.json"
    timeline = json.loads(timeline_path.read_text(encoding="utf-8"))
    sentences = timeline["sentences"]
    total = len(ref) / RATE
    db = loudness(lesson_dir / "audio_16k.wav")

    # 识别接口有时还占着临时文件，Windows 删不掉；删不掉就算了，系统会清
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp, ThreadPoolExecutor(WORKERS) as pool:
        counter = iter(range(10 ** 9))

        def listen(t0: float, t1: float) -> list[str]:
            path = Path(tmp) / f"{next(counter)}.wav"
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(RATE)
                w.writeframes(ref[int(t0 * RATE):int(t1 * RATE)].tobytes())
            return words_of(hear(path))

        body = [i for i, s in enumerate(sentences) if s["speaker"] != OUTSIDE and words_of(s["text"])]
        heard = dict(zip(body, pool.map(lambda i: listen(sentences[i]["start"], sentences[i]["end"]), body)))
        print(f"听了 {len(body)} 句；第一个词没听到的 {sum(heard[i][:1] != words_of(sentences[i]['text'])[:1] for i in body)} 句，"
              f"最后一个词没听到的 {sum(heard[i][-1:] != words_of(sentences[i]['text'])[-1:] for i in body)} 句")

        fixed, unfixed = [], []
        for i in body:
            s = sentences[i]
            want = words_of(s["text"])
            floor = sentences[i - 1]["end"] if i else 0.0
            heard_at = s["start"]
            if heard[i][:1] != want[:1]:
                tries = [round(s["start"] - STEP * k, 2) for k in range(1, int(MAX_MOVE / STEP) + 1)
                         if s["start"] - STEP * k >= floor]
                results = list(pool.map(lambda t: listen(t, s["end"]), tries))
                ok = [t for t, h in zip(tries, results) if h[:1] == want[:1]]
                if ok:
                    heard_at = max(ok)
                else:
                    unfixed.append((s["id"], "开头", s["text"], " ".join(heard[i])))
            # 真正开口的地方前面，要留够 PREROLL；现在留得不够（差 0.02 秒以上）才往前挪
            new = round(max(onset(db, heard_at, floor) - PREROLL, floor), 2)
            if new < s["start"] - 0.02:
                fixed.append((s["id"], "开头", s["start"], new, s["text"]))
                s["start"] = new
            if heard[i][-1:] != want[-1:]:
                ceil = sentences[i + 1]["start"] if i + 1 < len(sentences) else total
                tries = [round(s["end"] + STEP * k, 2) for k in range(1, int(MAX_MOVE / STEP) + 1)
                         if s["end"] + STEP * k <= ceil]
                results = list(pool.map(lambda t: listen(s["start"], t), tries))
                ok = [t for t, h in zip(tries, results) if h[-1:] == want[-1:]]
                if ok:
                    new = round(min(min(ok) + PAD, ceil), 2)
                    fixed.append((s["id"], "结尾", s["end"], new, s["text"]))
                    s["end"] = new
                else:
                    unfixed.append((s["id"], "结尾", s["text"], " ".join(heard[i])))

    manual = apply_manual(lesson_dir, sentences)
    timeline_path.write_text(json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"# 机器耳朵查句子边界 · {lesson}", "",
             f"听了 {len(body)} 句。挪好了 {len(fixed)} 处，挪到头也没听到的 {len(unfixed)} 处（要人耳查）。", "",
             "## 挪好了的", "", "| 句 | 哪头 | 原来 | 现在 | 这句 |", "|---|---|---|---|---|"]
    lines += [f"| {sid} | {side} | {old:.2f} | {new:.2f} | {text} |" for sid, side, old, new, text in fixed]
    lines += ["", "## 挪到头也没听到的", "", "| 句 | 哪头 | 这句 | 机器听到 |", "|---|---|---|---|"]
    lines += [f"| {sid} | {side} | {text} | {got} |" for sid, side, text, got in unfixed]
    lines += ["", "## 照人耳确认的改（bounds_manual.json）", ""] + [f"- {x}" for x in manual or ["没有要改的"]]
    (lesson_dir / "ear_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[2:]))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    (manual_only if "--manual" in sys.argv else main)(args[0] if args else "260821")
