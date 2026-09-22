"""比较两个模型生成的中文内容，产出一份并排对照表给 owner 挑。

挑的样本是难点句和难词：习惯用法（that's a shame、take your coffee、cut down on）、
本集的目标词（caffeine、decaf）、以及对 B1 学生偏难的词（grumpy、alertness、regain）。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from teach import mark_hard, translate  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MODELS = ["qwen3.8-flash", "deepseek-flash"]
SAMPLE_WORDS = [
    "shame", "take", "black", "white", "caffeine", "decaf", "decaffeinated",
    "grumpy", "alertness", "regain", "espresso", "alert", "cut", "down",
    "lucky", "recap", "shorten", "occasionally", "sweeter", "strong",
]


def pick_sentences(sentences: list[dict]) -> list[dict]:
    wanted = ["that's a shame", "take our coffee", "cut down on", "Lucky you",
              "first thing in the morning", "got a bit cool", "regain some energy",
              "grumpy", "espresso after dinner", "I don't care", "shorten", "have less of something"]
    picked = []
    for key in wanted:
        for s in sentences:
            if key.lower() in s["text"].lower() and s not in picked:
                picked.append(s)
                break
    return picked


def main(lesson: str) -> None:
    lesson_dir = ROOT / "lessons" / lesson
    timeline = json.loads((lesson_dir / "timeline.json").read_text(encoding="utf-8"))
    sentences = timeline["sentences"]
    context = " ".join(s["text"] for s in sentences)
    sample = pick_sentences(sentences)

    results: dict[str, dict] = {}
    for model in MODELS:
        print(f"跑 {model} ...")
        import time
        started = time.time()
        results[model] = {
            "zh": translate(sample, context, model),
            "hard": mark_hard(SAMPLE_WORDS, sentences, context, model),
            "secs": 0.0,
        }
        results[model]["secs"] = time.time() - started
        print(f"  用时 {results[model]['secs']:.1f} 秒")

    lines = [f"# 两个模型的中文内容对比 · {lesson}", "",
             "样本是难点句和难词。左右两列自己看，挑顺眼的那一个。", ""]
    lines.append("## 整句翻译")
    lines.append("")
    lines.append("| 英文原句 | " + " | ".join(MODELS) + " |")
    lines.append("|---|" + "---|" * len(MODELS))
    for s in sample:
        row = [s["text"]] + [results[m]["zh"].get(s["id"], "") for m in MODELS]
        lines.append("| " + " | ".join(row) + " |")

    lines += ["", "## 生词判断（备课时只判生词，意思等孩子点了再查）", "",
              "| 词 | " + " | ".join(MODELS) + " |",
              "|---|" + "---|" * len(MODELS)]
    for w in SAMPLE_WORDS:
        row = [w]
        for m in MODELS:
            row.append("生词" if results[m]["hard"].get(w, {}).get("hard") else "不算")
        lines.append("| " + " | ".join(row) + " |")

    lines += ["", "## 耗时", "",
              "| 模型 | 这份样本用时 |", "|---|---|"]
    for m in MODELS:
        lines.append(f"| {m} | {results[m]['secs']:.1f} 秒 |")

    out = lesson_dir / "model_compare.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"已写出 {out.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main(sys.argv[1] if len(sys.argv) > 1 else "260821")
