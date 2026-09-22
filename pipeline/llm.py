"""统一的大模型调用口，按模型名自动选平台。

两家都用 OpenAI 兼容接口：qwen 开头走百炼的兼容地址，deepseek 开头走 DeepSeek 自家地址。
百炼的老接口（dashscope.Generation）调 qwen3.8-flash 会报 url error，所以统一走兼容接口，
只有语音识别还留在老接口上（那边才有录音文件转写）。
密钥从 pipeline/keys.py 读，不打印、不进日志（红线）。
"""

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from keys import read_key  # noqa: E402


def _strip_fence(text: str) -> str:
    return re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()


def call(model: str, system: str, user: str) -> tuple[dict, float]:
    """返回（解析好的 JSON，耗时秒数）。"""
    from openai import OpenAI

    if model.startswith("deepseek"):
        client = OpenAI(api_key=read_key("deepseek"), base_url="https://api.deepseek.com")
    else:
        client = OpenAI(api_key=read_key("qwen"),
                        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
    started = time.time()
    # deepseek-flash 默认开着思考模式：一次 1.5 秒、先想 186 个字；关掉 0.4 秒（2026-09-22 量的）。
    # owner 要求不开（点词时现查，要快）
    extra = {"thinking": {"type": "disabled"}} if model.startswith("deepseek") else {}
    completion = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        response_format={"type": "json_object"},
        temperature=0.3,
        extra_body=extra,
    )
    text = completion.choices[0].message.content
    return json.loads(_strip_fence(text)), time.time() - started
