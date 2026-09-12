"""从 BBC 讲稿 PDF 里读出「谁说了什么」。

讲稿自己声明不是逐字稿，所以它只用来校正拼写、分句和说话人（决策 D1、D4，见 docs/decisions.md）。
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


def _clean_lines(pdf_path: Path) -> list[str]:
    lines: list[str] = []
    for page in PdfReader(pdf_path).pages:
        for raw in page.extract_text().splitlines():
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


def read_turns(pdf_path: Path) -> list[Turn]:
    lines = _clean_lines(pdf_path)
    names = _speaker_names(lines)
    turns: list[Turn] = []
    for line in lines:
        if line in names:
            turns.append(Turn(speaker=line, text=""))
        elif turns:
            turns[-1].text = (turns[-1].text + " " + line).strip()
    return [t for t in turns if t.text]
