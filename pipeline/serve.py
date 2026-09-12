"""本地网页服务，给播放器用。

为什么不用 python -m http.server：它不支持 Range 请求（从文件中间取一段）。
浏览器要跳到第 25 秒，必须能只取那一段；拿不到就跳不动，表现是「点下一句还是只播第一句」。
见 docs/lessons.md 2026-09-12 那条。

用法：<pywork python> pipeline/serve.py [端口]
"""

import os
import re
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHUNK = 64 * 1024


class RangeHandler(SimpleHTTPRequestHandler):
    """支持 Range 的静态文件服务。"""

    def end_headers(self) -> None:
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")  # 改了代码刷新就生效
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        range_header = self.headers.get("Range")
        path = self.translate_path(self.path)
        if not range_header or os.path.isdir(path):
            super().do_GET()
            return
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
        if not match:
            super().do_GET()
            return
        try:
            handle = open(path, "rb")
        except OSError:
            self.send_error(404)
            return
        with handle:
            size = os.fstat(handle.fileno()).st_size
            first, last = match.groups()
            if first:
                start = int(first)
                end = int(last) if last else size - 1
            else:  # bytes=-500 表示最后 500 字节
                start = max(0, size - int(last))
                end = size - 1
            end = min(end, size - 1)
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            self.send_response(206)
            self.send_header("Content-Type", self.guess_type(path))
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(end - start + 1))
            self.end_headers()
            handle.seek(start)
            remaining = end - start + 1
            while remaining > 0:
                chunk = handle.read(min(CHUNK, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass  # 安静点


def make_server(port: int = 8765) -> ThreadingHTTPServer:
    handler = partial(RangeHandler, directory=str(ROOT))
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = make_server(port)
    print(f"播放器地址：http://localhost:{port}/web/　（关掉这个窗口就停止）")
    server.serve_forever()
