"""实验：用百炼 qwen-audio-3.0-asr-flash-filetrans 识别一集，看时间戳能不能用。

为什么选这个模型（决策 D2，见 docs/decisions.md）：英文可用，句级和词级时间戳固定开启，
支持说话人分离，单文件上限 12 小时。同步版 qwen-audio-3.0-asr-flash 上限 5 分钟，
本集 6 分 02 秒放不下。

模型只收公网地址，所以先用 SDK 自带的临时存储把本地文件传上去，拿到 oss:// 地址，
再在请求头里打开 X-DashScope-OssResourceResolve。
"""

import json
import sys
from http import HTTPStatus
from pathlib import Path
from urllib import request

import dashscope
from dashscope.audio.asr import Transcription
from dashscope.utils.oss_utils import upload_file

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audio import probe, to_mono_16k_wav  # noqa: E402
from keys import read_key  # noqa: E402

MODEL = "qwen-audio-3.0-asr-flash-filetrans"
ROOT = Path(__file__).resolve().parent.parent


def transcribe(audio_path: Path, out_path: Path) -> dict:
    api_key = read_key("qwen")
    dashscope.api_key = api_key

    wav = out_path.parent / "audio_16k.wav"
    print(f"[1/4] 转单声道 16k：{wav.name}")
    to_mono_16k_wav(audio_path, wav)
    print(probe(wav))

    print("[2/4] 上传到百炼临时存储")
    oss_url = upload_file(MODEL, f"file://{wav}", api_key)
    print(f"      拿到地址：{oss_url.split('/')[0]}//...（省略）")

    print("[3/4] 提交识别任务")
    task = Transcription.async_call(
        model=MODEL,
        file_urls=[oss_url],
        language_hints=["en"],
        diarization_enabled=True,
        speaker_count=2,
        headers={"X-DashScope-OssResourceResolve": "enable"},
    )
    if task.status_code != HTTPStatus.OK:
        raise RuntimeError(f"提交失败：{task.status_code} {task.output}")
    print(f"      任务号：{task.output.task_id}")

    result = Transcription.wait(task=task.output.task_id)
    if result.status_code != HTTPStatus.OK:
        raise RuntimeError(f"识别失败：{result.status_code} {result.output}")

    print("[4/4] 下载结果")
    sub = result.output["results"][0]
    if sub["subtask_status"] != "SUCCEEDED":
        raise RuntimeError(f"子任务失败：{sub}")
    data = json.loads(request.urlopen(sub["transcription_url"]).read().decode("utf8"))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"      已存到 {out_path.relative_to(ROOT)}")
    return data


def summarize(data: dict) -> None:
    sentences = data["transcripts"][0]["sentences"]
    words = [w for s in sentences for w in s.get("words", [])]
    print(f"\n句子数：{len(sentences)}　词数：{len(words)}")
    speakers = sorted({s.get("speaker_id") for s in sentences})
    print(f"说话人标号：{speakers}")
    print("\n前 8 句：")
    for s in sentences[:8]:
        print(f"  [{s['begin_time']/1000:7.2f} - {s['end_time']/1000:7.2f}] "
              f"说话人{s.get('speaker_id')}  {s['text']}")
    if words:
        print("\n前 12 个词的时间：")
        for w in words[:12]:
            print(f"  [{w['begin_time']/1000:7.2f} - {w['end_time']/1000:7.2f}] {w['text']!r}")


if __name__ == "__main__":
    lesson = sys.argv[1] if len(sys.argv) > 1 else "260821"
    src = next((ROOT / "materials" / lesson).glob("*.mp3"))
    out = ROOT / "lessons" / lesson / "asr_raw.json"
    summarize(transcribe(src, out))
