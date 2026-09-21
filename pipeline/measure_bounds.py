"""量句子边界干不干净，用来比较改边界之前和之后。

只看声音本身，不依赖任何标记：
- 句末多播 20 / 40 / 80 毫秒就能听到声音的交界有几处（播放器停得不准时会带进下一句）；
- 句首之前 30 毫秒仍然很响的交界有几处（说明切在一个字中间，会切掉音头）。
「很响」指比说话时的典型音量低不到 20 分贝。

跑法：<pywork python> pipeline/measure_bounds.py [旧的 lesson.json] [课]
不给旧文件就只量现在的。旧文件可以这样取：git show <提交号>:lessons/260821/lesson.json > 某处
2026-09-21 的结果：识别原始时间 16/17/22 处、句首 80 处；精修后 12/14/21 处、句首 38 处（共 97 处交界）。
"""

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from refine_bounds import FRAME, loudness  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def measure(lesson_json: Path, db: np.ndarray) -> str:
    audible = np.percentile(db, 90) - 20

    def loud(t0: float, t1: float) -> bool:
        a, b = int(max(0, t0) / FRAME), int(max(0, t1) / FRAME)
        return b > a and db[a:b].max() >= audible

    sentences = json.loads(lesson_json.read_text(encoding="utf-8"))["sentences"]
    ends = [a["end"] for a in sentences[:-1]]
    starts = [b["start"] for b in sentences[1:]]
    bleed = [sum(loud(e, e + w) for e in ends) for w in (0.02, 0.04, 0.08)]
    head = sum(loud(s - 0.03, s) for s in starts)
    return (f"句末多播 20/40/80 毫秒就有声音 {bleed[0]}/{bleed[1]}/{bleed[2]} 处；"
            f"句首切在字中间 {head} 处（共 {len(ends)} 处交界）")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    lesson = sys.argv[2] if len(sys.argv) > 2 else "260821"
    db = loudness(ROOT / "lessons" / lesson / "audio_16k.wav")
    if len(sys.argv) > 1:
        print("之前：" + measure(Path(sys.argv[1]), db))
    print("现在：" + measure(ROOT / "lessons" / lesson / "lesson.json", db))
