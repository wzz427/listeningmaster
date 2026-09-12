"""读取本机密钥。

红线：密钥不入仓库、不流向输出。所以这里只负责读进内存返回，
调用方不许打印、不许写进日志或报错、不许放进命令行参数。
密钥文件 api-keys.txt 已在 .gitignore 第一行。
"""

from pathlib import Path

KEY_FILE = Path(__file__).resolve().parent.parent / "api-keys.txt"


def read_key(section: str) -> str:
    """取出 api-keys.txt 里 `#<section>` 下面第一行非空内容。"""
    if not KEY_FILE.exists():
        raise FileNotFoundError(f"找不到密钥文件：{KEY_FILE}")
    lines = KEY_FILE.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower() == f"#{section}".lower():
            for value in lines[i + 1:]:
                if value.strip():
                    return value.strip()
    raise KeyError(f"密钥文件里没有 #{section} 这一段")
