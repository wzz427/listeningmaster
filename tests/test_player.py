"""播放器的自动化验证：用 Playwright 真的打开页面、真的点按钮、真的看音频播到哪。

跑法：<pywork python> tests/test_player.py [--show]
加 --show 会显示浏览器窗口，看得见点击过程。

对应 specs/SPEC-001-player.md 的验收项，编号写在每个用例名里。
验的是真实可观察的行为：音频当前播到第几秒、屏幕上有没有那行字，
不验函数内部状态（指南第七章第 1 条）。
"""

import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from serve import make_server  # noqa: E402

PORT = 8799
URL = f"http://127.0.0.1:{PORT}/web/"
LESSON = "260821"

failures: list[str] = []
passes: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (passes if ok else failures).append(name)
    print(f"  {'通过' if ok else '未通过'}　{name}" + (f"　{detail}" if detail else ""))


def sentences(page) -> list[dict]:
    return page.evaluate("lesson.sentences")


def now(page) -> float:
    return page.evaluate("document.getElementById('audio').currentTime")


def paused(page) -> bool:
    return page.evaluate("document.getElementById('audio').paused")


def wait_playing(page) -> None:
    page.wait_for_function("!document.getElementById('audio').paused", timeout=5000)


def in_sentence(t: float, s: dict, slack: float = 0.35) -> bool:
    return s["start"] - slack <= t <= s["end"] + slack


def run(page) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(URL)
    page.wait_for_function("window.lesson !== null", timeout=10000)
    page.wait_for_function(
        "document.getElementById('audio').readyState >= 2", timeout=15000)
    body = [s for s in sentences(page) if s["speaker"] != "片头片尾"]

    print("\n【打开页面】")
    check("A0 页面加载没有报错", not errors, "; ".join(errors[:2]))
    check("A11 一打开就停在正文第一句",
          page.inner_text("#counter").startswith("第 1 句"),
          page.inner_text("#counter"))
    check("A2 默认不显示英文", page.is_hidden("#text"))

    print("\n【下一句 · 这一轮报的问题】")
    page.click("#nextBtn")
    wait_playing(page)
    page.wait_for_timeout(600)
    t = now(page)
    check("A-next 点下一句，真的播到了第 2 句", in_sentence(t, body[1]),
          f"现在 {t:.2f} 秒，第 2 句是 {body[1]['start']:.2f}-{body[1]['end']:.2f}")
    page.click("#nextBtn")
    page.wait_for_timeout(600)
    t = now(page)
    check("A-next2 再点一次，播到第 3 句", in_sentence(t, body[2]),
          f"现在 {t:.2f} 秒，第 3 句是 {body[2]['start']:.2f}-{body[2]['end']:.2f}")

    print("\n【重听本句】")
    long_idx = max(range(len(body)), key=lambda i: body[i]["end"] - body[i]["start"])
    page.evaluate(f"gotoSentence(lesson.sentences.indexOf(lesson.sentences.find(s=>s.id==={body[long_idx]['id']})))")
    wait_playing(page)
    page.wait_for_timeout(1500)
    page.click("#replayBtn")
    page.wait_for_timeout(300)
    t = now(page)
    check("A3 句中按重听，回到本句开头",
          abs(t - body[long_idx]["start"]) < 1.2,
          f"现在 {t:.2f} 秒，本句开头 {body[long_idx]['start']:.2f} 秒")

    page.evaluate(f"gotoSentence(lesson.sentences.findIndex(s=>s.id==={body[5]['id']}))")
    wait_playing(page)
    page.wait_for_timeout(200)
    page.click("#replayBtn")
    page.wait_for_timeout(300)
    t = now(page)
    check("A3b 刚开始就按重听，跳到上一句（反应延迟保护）",
          in_sentence(t, body[4]),
          f"现在 {t:.2f} 秒，上一句是 {body[4]['start']:.2f}-{body[4]['end']:.2f}")

    print("\n【精听模式每句停一下】")
    short_idx = min(range(3, len(body)), key=lambda i: body[i]["end"] - body[i]["start"])
    page.evaluate(f"gotoSentence(lesson.sentences.findIndex(s=>s.id==={body[short_idx]['id']}))")
    page.wait_for_function("document.getElementById('audio').paused", timeout=8000)
    t = now(page)
    check("A1 播到句末自动停住",
          abs(t - body[short_idx]["end"]) < 0.5,
          f"停在 {t:.2f} 秒，本句末尾 {body[short_idx]['end']:.2f} 秒")
    check("A1b 停住后按钮变成「继续 · 下一句」",
          "下一句" in page.inner_text("#playBtn"), page.inner_text("#playBtn"))
    page.click("#playBtn")
    page.wait_for_timeout(500)
    t = now(page)
    check("A1c 按下去真的进了下一句", in_sentence(t, body[short_idx + 1]),
          f"现在 {t:.2f} 秒")

    print("\n【看文字 · 看中文 · 点词】")
    page.evaluate(f"gotoSentence(lesson.sentences.findIndex(s=>s.id==={body[10]['id']}))")
    page.wait_for_timeout(200)
    check("A7b 没看英文之前，看中文的按钮不出现", page.is_hidden("#zhBtn"))
    page.click("#textBtn")
    shown = page.inner_text("#text")
    check("A5 显示的是整句英文", shown.strip() == body[10]["text"].strip(),
          f"屏幕上：{shown[:40]}")
    check("A6 出现「原速再听一遍」", page.is_visible("#againBtn"))
    check("A7b2 看过英文后，看中文的按钮出现了", page.is_visible("#zhBtn"))
    page.click("#zhBtn")
    check("A7b3 中文能显示出来", page.is_visible("#zh") and len(page.inner_text("#zh")) > 1,
          page.inner_text("#zh")[:30])
    page.click("#text w >> nth=0")
    check("A7 点词出现释义", page.is_visible("#wordbox") and len(page.inner_text("#wordZh")) > 0,
          f"{page.inner_text('#wordText')} → {page.inner_text('#wordZh')}")

    word = page.evaluate("lesson.sentences.find(s=>s.id===%d).words[0]" % body[10]["id"])
    page.click("#wordRaw")
    page.wait_for_timeout(250)
    t = now(page)
    check("A7c 播原声时，音频跳到了这个词的位置",
          abs(t - word["start"]) < 0.6,
          f"现在 {t:.2f} 秒，这个词在 {word['start']:.2f} 秒")

    print("\n【记录】")
    page.evaluate(f"gotoSentence(lesson.sentences.findIndex(s=>s.id==={body[12]['id']}))")
    page.wait_for_timeout(1300)  # 等过反应延迟保护的 1 秒，这样重听记在本句头上
    page.click("#replayBtn")
    page.wait_for_timeout(200)
    saved = page.evaluate(f"JSON.parse(localStorage.getItem('listening:{LESSON}') || '{{}}')")
    entry = saved.get(str(body[12]["id"]), {})
    check("A9 重听被记了下来", entry.get("replays", 0) >= 1, str(entry))

    page.evaluate(f"gotoSentence(lesson.sentences.findIndex(s=>s.id==={body[14]['id']}))")
    page.wait_for_timeout(200)
    page.click("#replayBtn")  # 刚开始就按，会跳到上一句
    page.wait_for_timeout(200)
    saved = page.evaluate(f"JSON.parse(localStorage.getItem('listening:{LESSON}') || '{{}}')")
    entry = saved.get(str(body[13]["id"]), {})
    check("A9b 刚开始就按重听，这次也记在上一句头上",
          entry.get("replays", 0) >= 1, str(entry))

    print("\n【慢速】")
    page.click("#rateBtn")
    rate = page.evaluate("document.getElementById('audio').playbackRate")
    check("A8 切换慢速生效", abs(rate - 0.8) < 0.01, f"倍速 {rate}")


def main() -> int:
    server = make_server(PORT)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    show = "--show" in sys.argv
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=not show,
            args=["--autoplay-policy=no-user-gesture-required"],
        )
        page = browser.new_page()
        try:
            run(page)
        finally:
            browser.close()
            server.shutdown()
    print(f"\n通过 {len(passes)} 项，未通过 {len(failures)} 项")
    if failures:
        print("未通过：" + "、".join(failures))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
