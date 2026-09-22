"""机器耳朵：把一段声音交给百炼语音识别，听出来是哪些词。

为什么需要它（2026-09-22）：按音量找句子和单词的边界，会被各种情况骗——
句首垫着片尾音乐，就找不到「安静」；k、t、p 这类音发之前嘴先闭住，那一下很安静，却在词的中间。
光核对「切口处安不安静」，切错了也发现不了；要听切下来的这一段说的是不是那几个词。
机器耳朵对很短的碎片不敏感，最后还得人耳抽查，但它能把明显的错先挑出来。

用 qwen3-asr-flash（同步接口，适合几秒的短片段）；本地文件直接给路径，SDK 会自己上传。
密钥从 pipeline/keys.py 读，不打印（红线）。
"""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from keys import read_key  # noqa: E402

MODEL = "qwen3-asr-flash"
# 机器耳朵的写法和讲稿不一样、但说的是同一个词
ALIASES = {"ok": "okay", "hmm": "mmm", "mm": "mmm", "hm": "mmm", "yep": "yep", "yup": "yep"}


def hear(path: Path, tries: int = 6) -> str:
    """失败了就等一会儿重试。一分钟里调得太多会被限流；限流时返回的不是识别结果，
    当成「没听到」就会误判（2026-09-22 踩过：前一百来次之后全部失败，句首一个都没修好）。"""
    import dashscope

    code = ""
    for k in range(tries):
        response = dashscope.MultiModalConversation.call(
            api_key=read_key("qwen"),
            model=MODEL,
            messages=[{"role": "user", "content": [{"audio": str(path)}]}],
            result_format="message",
            asr_options={"language": "en", "enable_itn": False},
        )
        try:
            return response.output.choices[0].message.content[0]["text"]
        except (AttributeError, IndexError, KeyError, TypeError):
            code = getattr(response, "code", "") or getattr(response, "status_code", "")
            time.sleep(2 * 2 ** k)
    raise RuntimeError(f"机器耳朵连试 {tries} 次都失败：{code}")


def words_of(text: str) -> list[str]:
    words = re.sub(r"[^a-z0-9' ]", " ", text.lower().replace("’", "'")).split()
    return [ALIASES.get(w, w) for w in words if w]
