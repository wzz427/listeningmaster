"""播放器的自动化验证：用 Playwright 真的打开页面、真的点按钮、真的看音频播到哪。

跑法：<pywork python> tests/test_player.py [--show] [--shots <目录>]
  --show        显示浏览器窗口，看得见点击过程
  --shots 目录   把几个关键画面截图存到这个目录，用来看界面

对应 specs/SPEC-001-player.md 的验收项，编号写在每个用例名里。
验的是真实可观察的行为：音频当前播到第几秒、有没有在播、音量有没有渐弱到零、屏幕上有没有那行字；
不验函数内部怎么写的（指南第七章第 1 条）。
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


def now(page) -> float:
    return page.evaluate("audio.currentTime")


def playing(page) -> bool:
    return page.evaluate("!audio.paused")


def wait_playing(page) -> None:
    page.wait_for_function("!audio.paused", timeout=5000)


def wait_paused(page, timeout=10000) -> None:
    page.wait_for_function("audio.paused", timeout=timeout)


def goto_body(page, n: int) -> None:
    """跳到正文第 n 句（从 0 数），和孩子点进度条是一回事。"""
    page.evaluate(f"gotoSentence(lesson.sentences.indexOf(body[{n}]))")


def in_sentence(t: float, s: dict, slack: float = 0.3) -> bool:
    return s["start"] - slack <= t <= s["end"] + slack


def shot(page, shots: Path | None, name: str) -> None:
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shots / f"{name}.png"))


def run(page, shots: Path | None) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(URL)
    page.wait_for_function("window.lesson !== null && document.querySelectorAll('.seg').length > 0",
                           timeout=15000)
    page.wait_for_function("audio.readyState >= 2", timeout=15000)
    body = page.evaluate("body")
    total = len(page.evaluate("lesson.sentences"))
    page.evaluate("audio.addEventListener('pause', () => { window.__pauseAt = audio.currentTime; "
                  "window.__gainAtPause = gain ? gain.gain.value : 1; })")
    shot(page, shots, "1-opened")

    print("\n【打开页面】")
    check("A0 页面加载没有报错", not errors, "; ".join(errors[:2]))
    check("A11 一打开就停在正文第一句", page.inner_text("#counter").startswith("第 1 句"),
          page.inner_text("#counter"))
    check("A2 默认不显示英文", page.is_hidden("#text"))
    page.click("#playBtn")
    wait_playing(page)
    page.wait_for_timeout(300)
    check("A11b 一打开按播放，从正文第一句开始播（不是片头）", in_sentence(now(page), body[0]),
          f"现在 {now(page):.2f} 秒，第 1 句从 {body[0]['start']:.2f} 秒开始")
    page.click("#playBtn")
    check("A15 进度条上每句一段", page.locator(".seg").count() == total,
          f"{page.locator('.seg').count()} 段 / {total} 句")

    print("\n【默认连续播放】")
    goto_body(page, 3)
    wait_playing(page)
    page.wait_for_function(f"audio.currentTime > {body[4]['start'] + 0.3}", timeout=10000)
    check("A16 播完一句不停，接着播下一句", playing(page) and page.inner_text("#counter").startswith("第 5 句"),
          f"{page.inner_text('#counter')}，{'在播' if playing(page) else '停了'}")

    print("\n【上一句 · 下一句 · 进度条】")
    page.click("#nextBtn")
    page.wait_for_timeout(400)
    t = now(page)
    check("A-next 点下一句，播到了下一句", in_sentence(t, body[5]),
          f"现在 {t:.2f} 秒，第 6 句是 {body[5]['start']:.2f}-{body[5]['end']:.2f}")
    page.keyboard.press("ArrowLeft")
    page.wait_for_timeout(400)
    t = now(page)
    check("A-prev 按左方向键回到上一句", in_sentence(t, body[4]), f"现在 {t:.2f} 秒")
    current = page.evaluate("Number(document.querySelector('.seg.current').dataset.i)")
    check("A15b 进度条上高亮的那段就是当前这句",
          current == page.evaluate("idx"), f"高亮第 {current} 段")
    seg = page.locator(f".seg[data-i=\"{page.evaluate('lesson.sentences.indexOf(body[30])')}\"]")
    box = seg.bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(400)
    t = now(page)
    check("A15c 点进度条上的一段，跳到那句开头", in_sentence(t, body[30]),
          f"现在 {t:.2f} 秒，第 31 句是 {body[30]['start']:.2f}-{body[30]['end']:.2f}")
    check("A19 在播时播放键显示暂停图标",
          page.evaluate("document.getElementById('iconPlay').hasAttribute('hidden') && "
                        "!document.getElementById('iconPause').hasAttribute('hidden')"))
    shot(page, shots, "2-playing")

    print("\n【重听本句】")
    longest = max(range(len(body)), key=lambda i: body[i]["end"] - body[i]["start"])
    goto_body(page, longest)
    wait_playing(page)
    page.wait_for_timeout(1500)
    page.click("#replayBtn")
    page.wait_for_timeout(250)
    t = now(page)
    check("A3 句中按重听，回到本句开头", abs(t - body[longest]["start"]) < 0.8,
          f"现在 {t:.2f} 秒，本句开头 {body[longest]['start']:.2f} 秒")
    goto_body(page, 8)
    wait_playing(page)
    page.wait_for_timeout(200)
    page.click("#replayBtn")
    page.wait_for_timeout(250)
    t = now(page)
    check("A3b 刚开始就按重听，回到上一句（反应延迟保护）", in_sentence(t, body[7]),
          f"现在 {t:.2f} 秒，上一句是 {body[7]['start']:.2f}-{body[7]['end']:.2f}")

    print("\n【每句停一下（打开开关后）】")
    page.click("#settingsBtn")
    page.click("label:has(#autoPause)")
    page.keyboard.press("Escape")
    check("A1 开关能打开", page.evaluate("document.getElementById('autoPause').checked"))
    short = min(range(3, len(body) - 1), key=lambda i: body[i]["end"] - body[i]["start"])
    goto_body(page, short)
    wait_paused(page)
    stopped = page.evaluate("window.__pauseAt")
    over = stopped - body[short]["end"]
    check("A1a 播到句末自动停住，不往下一句多播", -0.05 <= over <= 0.03,
          f"停在 {stopped:.3f} 秒，句末 {body[short]['end']:.3f} 秒，多播 {over * 1000:+.0f} 毫秒")
    check("A1b 停之前音量已经渐弱到零（不会带进下一句的声音）",
          page.evaluate("window.__gainAtPause") < 0.05,
          f"停的那一刻音量 {page.evaluate('window.__gainAtPause'):.3f}")
    check("A1c 停住后按钮写着「下一句」", page.inner_text("#playLabel") == "下一句",
          page.inner_text("#playLabel"))
    page.click("#playBtn")
    page.wait_for_timeout(300)
    check("A1d 再按一下进了下一句", in_sentence(now(page), body[short + 1]), f"现在 {now(page):.2f} 秒")
    wait_paused(page)
    page.click("#settingsBtn")
    page.click("label:has(#autoPause)")
    page.keyboard.press("Escape")

    print("\n【看文字 · 看中文 · 点词】")
    goto_body(page, 10)
    page.wait_for_timeout(200)
    check("A7b 没看英文之前，看中文的按钮不出现", page.is_hidden("#zhBtn"))
    page.click("#textBtn")
    shown = page.inner_text("#text")
    check("A5 显示的是整句英文", shown.strip() == body[10]["text"].strip(), f"屏幕上：{shown[:40]}")
    check("A6 出现「原速再听一遍」", page.is_visible("#againBtn"))
    check("A7b2 看过英文后，看中文的按钮出现了", page.is_visible("#zhBtn"))
    wait_paused(page)
    check("A17 连续播放时看了文字，这句播完就停，不往下走",
          in_sentence(now(page), body[10], slack=0.05), f"停在 {now(page):.2f} 秒")
    page.click("#zhBtn")
    check("A7b3 中文能显示出来", page.is_visible("#zh") and len(page.inner_text("#zh")) > 1,
          page.inner_text("#zh")[:30])
    page.click("#text w >> nth=1")
    check("A7 点词出现释义", page.is_visible("#wordbox") and len(page.inner_text("#wordZh")) > 0,
          f"{page.inner_text('#wordText')} → {page.inner_text('#wordZh')}")
    page.wait_for_timeout(250)  # 等弹出动画走完再截图
    box_w, card_w = page.locator("#wordbox").bounding_box(), page.locator("#zh").bounding_box()
    check("A7e 单词卡不挡住中文翻译",
          box_w["y"] + box_w["height"] <= card_w["y"] or box_w["y"] >= card_w["y"] + card_w["height"])
    shot(page, shots, "3-text-word")
    word = body[10]["words"][1]
    before = now(page)
    page.click("#wordRaw")
    page.wait_for_timeout(120)
    t = now(page)
    check("A7c 播原声时，音频跳到了这个词的位置", abs(t - word["start"]) < 0.3,
          f"现在 {t:.2f} 秒，这个词在 {word['start']:.2f} 秒")
    wait_paused(page)
    page.wait_for_timeout(100)
    check("A7d 播完这个词，回到原来的位置", abs(now(page) - before) < 0.05,
          f"回到 {now(page):.2f} 秒，原来 {before:.2f} 秒")

    print("\n【记录】")
    goto_body(page, 12)
    page.wait_for_timeout(1300)  # 等过 1 秒的反应延迟保护，这样重听记在本句头上
    page.click("#replayBtn")
    page.wait_for_timeout(200)
    saved = page.evaluate(f"JSON.parse(localStorage.getItem('listening:{LESSON}') || '{{}}')")
    check("A9 重听被记了下来", saved.get(str(body[12]["id"]), {}).get("replays", 0) >= 1)
    goto_body(page, 14)
    page.wait_for_timeout(200)
    page.click("#replayBtn")
    page.wait_for_timeout(200)
    saved = page.evaluate(f"JSON.parse(localStorage.getItem('listening:{LESSON}') || '{{}}')")
    check("A9b 刚开始就按重听，这次记在上一句头上",
          saved.get(str(body[13]["id"]), {}).get("replays", 0) >= 1)
    check("A15d 重听过的句子在进度条上有小圆点",
          page.locator(".seg.stuck").count() >= 2, f"{page.locator('.seg.stuck').count()} 段")

    print("\n【语速】")
    page.click(".speed-btn[data-rate='0.8']")
    check("A8 切到 0.8 生效", abs(page.evaluate("audio.playbackRate") - 0.8) < 0.01)
    page.click(".speed-btn[data-rate='1']")

    print("\n【家长检查】")
    page.click("#checkBtn")
    target = page.evaluate("lesson.sentences.indexOf(body[20])")
    page.click(f"#checkList li[data-i=\"{target}\"]")
    wait_playing(page)
    names = page.evaluate("speakerClass")
    avatar = page.evaluate("document.getElementById('avatar').className")
    check("A20 头像颜色跟着说话人走", avatar == f"avatar {names[body[20]['speaker']]}",
          f"{body[20]['speaker']} → {avatar}")
    grid = page.locator("#timeline").bounding_box()
    drawer = page.locator("#checkPanel").bounding_box()
    check("A18b 打开家长检查时，进度条不被挡住", grid["x"] + grid["width"] <= drawer["x"] + 1,
          f"进度条右端 {grid['x'] + grid['width']:.0f}，面板左端 {drawer['x']:.0f}")
    page.wait_for_timeout(400)
    shot(page, shots, "4-check")
    wait_paused(page)
    t = page.evaluate("window.__pauseAt")
    check("A18 点一句只播这一句，播到句末就停", abs(t - body[20]["end"]) < 0.04,
          f"停在 {t:.3f} 秒，句末 {body[20]['end']:.3f} 秒")


def main() -> int:
    server = make_server(PORT)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    show = "--show" in sys.argv
    shots = Path(sys.argv[sys.argv.index("--shots") + 1]) if "--shots" in sys.argv else None
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not show,
                                    args=["--autoplay-policy=no-user-gesture-required"])
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        try:
            run(page, shots)
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
