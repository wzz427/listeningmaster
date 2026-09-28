"""从 BBC 讲稿里读出「谁说了什么」。

讲稿自己声明不是逐字稿，所以它只用来校正拼写、分句和说话人（决策 D1、D4，见 docs/decisions.md）。
两种来路（SPEC-009）：BBC 的讲稿 PDF；家长上传时粘贴的纯文本（transcript.txt，每句「说话人: 内容」或
「说话人」单独一行都认）。两边走同一套解析，PDF 只是先抽成文本行。
"""

import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

# 页眉页脚和版权行，按前缀丢弃
BOILERPLATE = (
    "BBC LEARNING ENGLISH", "Real Easy English", "bbclearningenglish.com",
    "This is a transcript", "©British Broadcasting", "© British Broadcasting",
)


@dataclass
class Turn:
    speaker: str
    text: str


def _clean_lines(path: Path) -> list[str]:
    if path.suffix.lower() == ".txt":  # 纯文本讲稿：行当 PDF 抽出来的行用
        raw_lines: list[str] = []
        for raw in path.read_text(encoding="utf-8").splitlines():
            m = re.fullmatch(r"([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)?):\s*(.+)", raw.strip())
            if m:  # 「Georgie: 内容」拆成说话人行＋内容行，跟 PDF 的版式对齐
                raw_lines += [m.group(1), m.group(2)]
            else:
                raw_lines.append(raw)
    else:
        raw_lines = [line for page in PdfReader(path).pages for line in page.extract_text().splitlines()]
    lines: list[str] = []
    for raw in raw_lines:
        line = raw.strip()
        if not line or line.startswith(BOILERPLATE) or re.fullmatch(r"Page \d+ of \d+", line):
            continue
        lines.append(line)
    return lines


def _speaker_names(lines: list[str]) -> set[str]:
    """说话人行的特征：一两个词、首字母大写、没有句末标点，而且反复出现。"""
    counts = Counter(
        line for line in lines
        if re.fullmatch(r"[A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)?", line)
    )
    return {name for name, n in counts.items() if n >= 3}


def read_turns(path: Path) -> list[Turn]:
    lines = _clean_lines(path)
    names = _speaker_names(lines)
    turns: list[Turn] = []
    for line in lines:
        if line in names:
            turns.append(Turn(speaker=line, text=""))
        elif turns:
            turns[-1].text = (turns[-1].text + " " + line).strip()
    return [t for t in turns if t.text]
