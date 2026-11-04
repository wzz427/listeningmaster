"""造无讲稿考卷的考题和答案（tests/fixtures/free/，SPEC-013 R10）。

为什么单独一个程序：金样考卷 tests/test_slicing.py 的 A6 要离线重放无讲稿路，得先有一套
不联网的输入——①识别结果：四课去掉 speaker_count 重识别的试跑（ablation/diarization/
qwen-nocount_*.json，gitignore 挡着，这里拷进仓库一份当考题）；②大模型回答的缓存：
巨词、起名各问一次 deepseek-flash，回答落 llm_cache.json；③首次跑出的 free 金样
（改了 no_transcript.py 的提示词或规则、金样要跟着变时重跑本程序，花几分钱）。

识别的原始出处丢了也不怕：考题识别已在 fixtures 里，重跑只用它、不再碰 ablation/。

跑法：<pywork python> tests/make_free_fixtures.py   （联网，调大模型，几分钱）
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline" / "slicing"))
import no_transcript  # noqa: E402

LESSONS = ["260821", "250918", "261009", "250123"]
FIXTURES = ROOT / "tests" / "fixtures" / "free"


def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for lesson in LESSONS:
        src = ROOT / "ablation" / "diarization" / f"qwen-nocount_{lesson}.json"
        if not src.exists():   # ablation/ 是 gitignore 的临时处；重跑时用仓库里那份考题
            src = FIXTURES / f"{lesson}_asr.json"
        tmp = Path(tempfile.mkdtemp())
        lesson_dir = tmp / "lessons" / lesson
        material_dir = tmp / "materials" / lesson
        lesson_dir.mkdir(parents=True)
        material_dir.mkdir(parents=True)
        shutil.copy2(src, lesson_dir / "asr_raw.json")
        for f in (ROOT / "materials" / lesson).glob("*.mp3"):
            shutil.copy2(f, material_dir / f.name)   # timeline 的 audio 字段要文件名
        if (FIXTURES / f"{lesson}_llm_cache.json").exists():
            # 上一轮的回答先垫上：问法没变（提示词、识别原句都没动）就不重新问，省钱也稳金样
            shutil.copy2(FIXTURES / f"{lesson}_llm_cache.json", lesson_dir / "llm_cache.json")
        try:
            stats = no_transcript.build(lesson, root=tmp)
            timeline = json.loads((lesson_dir / "timeline.json").read_text(encoding="utf8"))
            if (lesson_dir / "llm_cache.json").exists():
                shutil.copy2(lesson_dir / "llm_cache.json", FIXTURES / f"{lesson}_llm_cache.json")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        shutil.copy2(src, FIXTURES / f"{lesson}_asr.json")
        (FIXTURES / f"{lesson}_gold.json").write_text(
            json.dumps(timeline, ensure_ascii=False, indent=2), encoding="utf8")
        print(f"{lesson}：{stats['sentences']} 句、{stats['speakers']} 位说话人、并半句 {stats['merged']} 处；"
              f"{stats['labels']}；{stats['note']}\n")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
