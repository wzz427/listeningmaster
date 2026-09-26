"""播放器的自动化验证：用 Playwright 真的打开页面、真的点按钮、真的看音频播到哪。

跑法：<pywork python> tests/test_player.py [--show] [--shots <目录>]
  --show        显示浏览器窗口，看得见点击过程
  --shots 目录   把几个关键画面截图存到这个目录，用来看界面

对应 specs/ 下各份规格的验收项（A 开头的编号），编号写在每个用例名开头；tests/test_docs.py 核对两边对得上。
验的是真实可观察的行为：音频当前播到第几秒、有没有在播、音量有没有渐弱到零、屏幕上有没有那行字；
不验函数内部怎么写的（指南第七章第 1 条）。
"""

import re
import sys
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
from serve import make_server  # noqa: E402
import stable_copy  # noqa: E402

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


def wait_paused(page, timeout=20000) -> None:  # 最长的一句 11 秒
    page.wait_for_function("audio.paused", timeout=timeout)


def goto_body(page, n: int, flow: bool = False) -> None:
    """跳到正文第 n 句（从 0 数）。
    默认只播这一句，和孩子点上一句、下一句、进度条是一回事；flow=True 从这句开始连续往下播。"""
    fn = "playFrom" if flow else "playOne"
    page.evaluate(f"{fn}(lesson.sentences.indexOf(body[{n}]))")


def in_sentence(t: float, s: dict, slack: float = 0.3) -> bool:
    return s["start"] - slack <= t <= s["end"] + slack


def clock_text(seconds: float) -> str:
    """和 app.js 的 clock 一样：秒数写成 m:ss。"""
    m, s = divmod(max(0, int(seconds)), 60)
    return f"{m}:{s:02d}"


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
    page.wait_for_timeout(800)  # 等进场动画走完再截图
    shot(page, shots, "1-opened")

    print("\n【打开页面】")
    check("A0 页面加载没有报错", not errors, "; ".join(errors[:2]))
    check("A11 一打开就停在正文第一句", page.inner_text("#counter").startswith("第 1 段 · 第 1 句"),
          page.inner_text("#counter"))
    check("A2 默认不显示英文", page.is_hidden("#text"))
    check("A59 卡片平时只有声浪，没有常驻的引导文字",
          "先用耳朵" not in page.inner_text("#card") and page.locator("#hint .bars i").count() == 11,
          page.inner_text("#card").strip()[:30])
    page.click("#playBtn")
    wait_playing(page)
    page.wait_for_timeout(300)
    check("A11b 一打开按播放，从正文第一句开始播（不是片头）", in_sentence(now(page), body[0]),
          f"现在 {now(page):.2f} 秒，第 1 句从 {body[0]['start']:.2f} 秒开始")
    page.click("#playBtn")
    in_part = page.evaluate("part().last - part().first + 1")
    check("A15 下面那条只画当前这段，每句一小段", page.locator(".seg").count() == in_part < total,
          f"{page.locator('.seg').count()} 小段 / 这段 {in_part} 句 / 整集 {total} 句")

    print("\n【按播放键是连续播】")
    goto_body(page, 3, flow=True)
    wait_playing(page)
    page.wait_for_function(f"audio.currentTime > {body[4]['start'] + 0.3}", timeout=10000)
    check("A16 播完一句不停，接着播下一句", playing(page) and "第 5 句" in page.inner_text("#counter"),
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
    pick = page.evaluate("Math.floor((part().first + part().last) / 2)")
    target = page.evaluate(f"lesson.sentences[{pick}]")
    box = page.locator(f".seg[data-i=\"{pick}\"]").bounding_box()
    page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_timeout(400)
    t = now(page)
    check("A15c 点进度条上的一小段，跳到那句开头", in_sentence(t, target),
          f"现在 {t:.2f} 秒，那句是 {target['start']:.2f}-{target['end']:.2f}")
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
    wait_paused(page)
    stopped = page.evaluate("window.__pauseAt")
    check("A3c 重听只播这一句，播完就停", abs(stopped - body[7]["end"]) < 0.04,
          f"停在 {stopped:.3f} 秒，句末 {body[7]['end']:.3f} 秒")

    print("\n【按句子键只播一句】")
    check("A1 设置里没有「每句播完停一下」开关了", page.locator("#autoPause").count() == 0)
    # 挑一句短的，它和后面两句都不是段末（段末那句连续播到这里会换成「这段听完了」，另有用例）
    section_ends = {x["last"] for x in page.evaluate("lesson.sections")}
    usable = [i for i in range(3, len(body) - 3)
              if all(body[j]["id"] not in section_ends for j in (i, i + 1, i + 2))]
    short = min(usable, key=lambda i: body[i]["end"] - body[i]["start"])
    goto_body(page, short - 1, flow=True)
    wait_playing(page)
    page.click("#nextBtn")  # 连续播着按下一句
    wait_paused(page)
    stopped = page.evaluate("window.__pauseAt")
    over = stopped - body[short]["end"]
    check("A1a 连续播着按下一句，只播那一句，播完停在句末，不往下一句多播", -0.05 <= over <= 0.03,
          f"停在 {stopped:.3f} 秒，句末 {body[short]['end']:.3f} 秒，多播 {over * 1000:+.0f} 毫秒")
    check("A1b 停之前音量已经渐弱到零（不会带进下一句的声音）",
          page.evaluate("window.__gainAtPause") < 0.05,
          f"停的那一刻音量 {page.evaluate('window.__gainAtPause'):.3f}")
    check("A1c 停住后播放键写着「播放」，状态牌写着「停在这句末尾」",
          page.inner_text("#playLabel") == "播放" and page.inner_text("#stateTag") == "停在这句末尾",
          f"{page.inner_text('#playLabel')} / {page.inner_text('#stateTag')}")
    page.click("#nextBtn")
    page.wait_for_timeout(150)
    check("A1d 再按下一句，只播下一句", in_sentence(now(page), body[short + 1])
          and page.inner_text("#stateTag") == "只播这一句",
          f"现在 {now(page):.2f} 秒，{page.inner_text('#stateTag')}")
    wait_paused(page)
    stopped = page.evaluate("window.__pauseAt")
    check("A1e 播完那句又停住", abs(stopped - body[short + 1]["end"]) < 0.04,
          f"停在 {stopped:.3f} 秒，句末 {body[short + 1]['end']:.3f} 秒")
    page.click("#playBtn")
    page.wait_for_function(f"audio.currentTime > {body[short + 3]['start'] + 0.1}", timeout=15000)
    check("A1f 停在句末按播放，从下一句开始连续往下播", playing(page),
          f"已播到 {now(page):.2f} 秒，越过了第 {short + 3} 句的开头 {body[short + 3]['start']:.2f} 秒")
    page.click("#playBtn")

    print("\n【看文字 · 看中文 · 点词】")
    goto_body(page, 10, flow=True)
    page.wait_for_timeout(200)
    check("A7b 没看英文之前，看中文的按钮不出现", page.is_hidden("#zhBtn"))
    page.click("#textBtn")
    shown = page.inner_text("#text")
    check("A5 显示的是整句英文", shown.strip() == body[10]["text"].strip(), f"屏幕上：{shown[:40]}")
    check("A6 看过文字后「重听本句」亮起来，没有单独的「原速再听一遍」",
          page.locator("#replayBtn.nudge").count() == 1 and page.locator("#againBtn").count() == 0)
    check("A7b2 看过英文后，看中文的按钮出现了", page.is_visible("#zhBtn"))
    wait_paused(page)
    check("A17 连续播放时看了文字，这句播完就停，不往下走",
          in_sentence(now(page), body[10], slack=0.05), f"停在 {now(page):.2f} 秒")
    page.click("#zhBtn")
    check("A7b3 中文能显示出来", page.is_visible("#zh") and len(page.inner_text("#zh")) > 1,
          page.inner_text("#zh")[:30])
    asks, mores = [], []  # 点词时去查了几次那一行、几次展开的
    page.on("request", lambda r: asks.append(r.url) if r.url.endswith("/api/explain") else None)
    page.on("request", lambda r: mores.append(r.url) if r.url.endswith("/api/more") else None)
    page.click("#text w >> nth=1")
    page.wait_for_timeout(80)
    loaded = "!document.getElementById('wordZh').classList.contains('loading')"
    check("A7r 那一行备课时就写好了，点词马上出来，不用去查（决策 D30）",
          not asks and page.evaluate(loaded), f"查了 {len(asks)} 次")
    missing = page.evaluate("lesson.sentences.reduce((n, s) => n + s.words.filter((w, k) => "
                            "!(s.notes || []).some((x) => x.words.includes(k))).length, 0)")
    total = page.evaluate("lesson.sentences.reduce((n, s) => n + s.words.length, 0)")
    check("A7u 备课时每个词都写了那一行", missing <= total * 0.02, f"{total} 个词里漏了 {missing} 个")
    line = page.inner_text(".word-line")
    check("A7 点词出现一行：词性、英式音标、这句里的意思（决策 D30）",
          page.is_visible("#wordbox") and page.is_visible("#wordPos") and len(page.inner_text("#wordPos")) >= 2
          and re.fullmatch(r"/[^/]+/", page.inner_text("#wordIpa")) is not None
          and len(page.inner_text("#wordZh")) >= 1 and "没查到" not in line and "这句里" not in page.inner_text("#wordbox"),
          f"{page.inner_text('#wordText')} → {line}")
    faces = page.evaluate("document.fonts.load('16px \"Noto Serif IPA\"', 'ˈəʊ').then((f) => f.length)")
    family = page.evaluate("getComputedStyle(document.getElementById('wordIpa')).fontFamily")
    check("A7t 音标用带音标符号的字体（放在本地，不连外网）", faces >= 1 and family.startswith('"Noto Serif IPA"'),
          f"载入 {faces} 个字体，{family}")
    page.wait_for_timeout(250)  # 等弹出动画走完再截图
    box_w, card_w = page.locator("#wordbox").bounding_box(), page.locator("#zh").bounding_box()
    check("A7e 单词卡不挡住中文翻译",
          box_w["y"] + box_w["height"] <= card_w["y"] or box_w["y"] >= card_w["y"] + card_w["height"])
    shot(page, shots, "3-text-word")
    page.evaluate("delete notes[`${cur().id}:2`]; 0")  # 装作备课漏了第 3 个词
    with page.expect_response(lambda r: r.url.endswith("/api/explain")) as asked:
        page.click("#text w >> nth=2")
    page.wait_for_function(loaded, timeout=20000)
    check("A7v 备课漏了的词，点了再补查", asked.value.ok and len(page.inner_text("#wordZh")) >= 1
          and "没查到" not in page.inner_text("#wordZh"), f"{page.inner_text('#wordText')} → {page.inner_text('.word-line')}")
    check("A7j 单词卡上只有朗读，没有「这句里的原声」（切不准，2026-09-22 拿掉了）",
          page.locator("#wordRaw").count() == 0 and page.is_visible("#wordTts"))
    page.evaluate("window.__spoke = 0; if (window.speechSynthesis) speechSynthesis.speak = () => window.__spoke++; 0")  # 末尾不能是函数，不然 Playwright 会调它
    with page.expect_response(lambda r: "/tts/" in r.url) as got:
        page.click("#wordTts")
    page.wait_for_function("voice.currentTime > 0.1", timeout=5000)
    check("A7k 单个词的「听朗读」放的是发音词典里拷来的谷歌英音，不用浏览器自带的朗读（大陆不翻墙读不出来）",
          got.value.ok and "/tts/google_en-GB/" in got.value.url and page.evaluate("window.__spoke") == 0,
          f"{got.value.url.split('/lessons/')[-1]}（{got.value.status}），浏览器朗读被叫了 {page.evaluate('window.__spoke')} 次")
    page.keyboard.press("Escape")
    page.click("#replayBtn")
    page.wait_for_function("!audio.paused", timeout=3000)
    page.click("#text w >> nth=1")
    page.click("#wordTts")
    page.wait_for_timeout(100)
    check("A7l 句子正在放时点「听朗读」，句子先停下，不叠在一起", page.evaluate("audio.paused"),
          f"停在 {now(page):.2f} 秒")
    page.keyboard.press("Escape")
    files = page.evaluate("(lesson.tts || {}).files || {}")
    keys = set(page.evaluate("lesson.sentences.flatMap((s) => s.words.map((w) => w.key)).filter(Boolean)"))
    here = Path(__file__).resolve().parent.parent / "lessons" / LESSON
    broken = sorted(k for k, f in files.items() if not (here / f).exists())
    check("A7m 备课时从发音词典拷来的朗读文件都在；词典里没有的点了再读",
          not broken and len(files) >= 0.9 * len(keys), f"拷来 {len(files)} 个 / 课文 {len(keys)} 个词，坏的 {broken[:5]}")

    # 词组：第 66 句 Cut down on, You mean have less? 点第二个词 down
    n66 = page.evaluate("lesson.sentences.findIndex((s) => s.id === 66)")
    page.evaluate(f"playOne({n66}); audio.pause()")
    page.click("#textBtn")
    page.click("#text w >> nth=1")
    page.wait_for_function(loaded, timeout=20000)
    check("A7n 点词组里的一个词，讲的是整个词组，词组里的词一起亮",
          page.inner_text("#wordText").lower().startswith("cut down on") and page.locator("#text w.picked").count() == 3,
          f"{page.inner_text('#wordText')}：{page.inner_text('.word-line')[:40]}（亮了 {page.locator('#text w.picked').count()} 个词）")
    check("A7o 点词只出那一行；展开的内容先收着，也还没去查（决策 D30）",
          page.is_hidden("#wordMore") and page.is_visible("#wordMoreBtn") and not mores, f"已经查了 {len(mores)} 次展开")
    page.wait_for_timeout(250)  # 等弹出动画走完再量位置，不然量到的是动画里的位移
    box_before = page.locator("#wordbox").bounding_box()
    with page.expect_response(lambda r: r.url.endswith("/api/more"), timeout=30000) as got_more:
        page.click("#wordMoreBtn")
    page.wait_for_function("!document.getElementById('moreBody').hidden", timeout=20000)
    page.wait_for_timeout(250)
    box = page.locator("#wordbox").bounding_box()
    check("A7p 点展开才去查，看到常见意思（标出这句用的）、搭配、例句，卡片没挪窝、没出屏幕",
          got_more.value.ok and page.is_visible("#wordMore") and page.locator("#moreSenses li.used").count() == 1
          and page.locator("#moreColl li").count() >= 1 and len(page.inner_text("#moreEx")) > 3
          and abs(box["x"] - box_before["x"]) < 1 and abs(box["y"] - box_before["y"]) < 1
          and box["y"] >= 0 and box["y"] + box["height"] <= page.viewport_size["height"],
          f"{page.locator('#moreSenses li').count()} 个意思，{page.locator('#moreColl li').count()} 个搭配，"
          f"展开前 y={box_before['y']:.0f}、展开后 y={box['y']:.0f}")
    shot(page, shots, "3b-word-more")
    with page.expect_response(lambda r: "/tts/" in r.url, timeout=30000) as got:
        page.click("#wordTts")
    check("A7q 词组的朗读读整个词组（百炼 Emily 现读，存下来）",
          got.value.ok and got.value.url.endswith("/tts/bailian_emily/cut_down_on.mp3"),
          got.value.url.split("/lessons/")[-1])
    page.keyboard.press("Escape")
    asks.clear()
    page.click("#text w >> nth=0")
    page.wait_for_timeout(300)
    mores.clear()
    page.click("#wordMoreBtn")
    page.wait_for_timeout(300)
    check("A7s 点词组里的另一个词，那一行和展开的都直接出来，不再去查",
          not asks and not mores and page.inner_text("#wordText").lower().startswith("cut down on")
          and page.locator("#moreSenses li").count() >= 1 and page.is_visible("#moreSenses"),
          f"又查了 {len(asks)} 次那一行、{len(mores)} 次展开")
    page.keyboard.press("Escape")

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
    goto_body(page, 2)
    page.click("#replayBtn")
    page.click("#replayBtn")  # 旧版第二次重听同一句会自动降到 0.8，owner 2026-09-26 拿掉了
    gears = page.evaluate("[...document.querySelectorAll('.speed-btn')].map((b) => b.dataset.rate)")
    check("A4 速度只归用户：挡位 0.6 / 0.8 / 1.0，重听两遍也不自动变，设置里没有自动放慢的开关",
          gears == ["0.6", "0.8", "1"] and abs(page.evaluate("audio.playbackRate") - 1) < 0.01
          and page.locator("#autoSlow").count() == 0,
          f"挡位 {gears}，速度 {page.evaluate('audio.playbackRate')}")
    page.click(".speed-btn[data-rate='0.8']")
    check("A8 切到 0.8 生效", abs(page.evaluate("audio.playbackRate") - 0.8) < 0.01)
    page.click(".speed-btn[data-rate='1']")

    sections_part(page, shots, body)

    print("\n【全文】")
    check("A18c 面板叫「全文」", page.inner_text("#fullBtn") == "全文", page.inner_text("#fullBtn"))
    page.click("#fullBtn")
    check("A18d 全文按段分组", page.locator("#fullList li.group").count() == page.evaluate("parts.length"),
          f"{page.locator('#fullList li.group').count()} 组")
    target = page.evaluate("lesson.sentences.indexOf(body[20])")
    page.click(f"#fullList li.line[data-i=\"{target}\"]")
    wait_playing(page)
    names = page.evaluate("speakerClass")
    avatar = page.evaluate("document.getElementById('avatar').className")
    check("A20 头像颜色跟着说话人走", avatar == f"avatar {names[body[20]['speaker']]}",
          f"{body[20]['speaker']} → {avatar}")
    page.wait_for_timeout(500)  # 面板滑入、播放器让位都有动画，走完再量（早量了会时过时不过）
    grid = page.locator("#timeline").bounding_box()
    drawer = page.locator("#fullPanel").bounding_box()
    check("A18b 打开全文时，进度条不被挡住", grid["x"] + grid["width"] <= drawer["x"] + 1,
          f"进度条右端 {grid['x'] + grid['width']:.0f}，面板左端 {drawer['x']:.0f}")
    page.wait_for_timeout(400)
    shot(page, shots, "5-full")
    wait_paused(page)
    t = page.evaluate("window.__pauseAt")
    check("A18 点一句只播这一句，播到句末就停", abs(t - body[20]["end"]) < 0.04,
          f"停在 {t:.3f} 秒，句末 {body[20]['end']:.3f} 秒")
    page.keyboard.press("Escape")
    drag_part(page, shots)
    update_part(page, shots)


def drag_part(page, shots: Path | None) -> None:
    """SPEC-001 R23：两条进度条都能拖。用真的鼠标按下、拖动、松开。"""
    print("\n【拖进度】")
    sentences = page.evaluate("lesson.sentences")
    parts = page.evaluate("parts")

    def bar() -> dict:
        return page.locator("#timeline").bounding_box()

    def x_of(t: float) -> float:   # 下面那条上，时间 t 在哪个横坐标
        q = parts[page.evaluate("shownPart")]
        box = bar()
        return box["x"] + (t - q["t0"]) / (q["t1"] - q["t0"]) * box["width"]

    def playhead_x() -> float:
        box = page.locator("#playhead").bounding_box()
        return box["x"] + box["width"] / 2

    def press_and_drag(x0: float, x1: float, y: float, release: bool = True) -> None:
        page.mouse.move(x0, y)
        page.mouse.down()
        page.mouse.move(x0 + (8 if x1 > x0 else -8), y, steps=2)
        page.mouse.move(x1, y, steps=10)
        if release:
            page.mouse.up()
        page.wait_for_timeout(300)

    def longest_in_shown(skip: set[int]) -> int:
        q = parts[page.evaluate("shownPart")]
        pool = [i for i in range(q["first"], q["last"] + 1) if i not in skip]
        return max(pool, key=lambda i: sentences[i]["end"] - sentences[i]["start"])

    # A52 / A56：暂停着拖，松手停在松手的位置，不播，也没被当成点了一下
    goto_body(page, 3)
    wait_paused(page)
    here = page.evaluate("idx")
    j = longest_in_shown({here})
    target = sentences[j]["start"] + 0.6 * (sentences[j]["end"] - sentences[j]["start"])
    y = bar()["y"] + bar()["height"] / 2
    press_and_drag(playhead_x(), x_of(target), y, release=False)
    page.wait_for_timeout(200)
    shot(page, shots, "11-dragging")
    page.mouse.up()
    page.wait_for_timeout(400)
    t = now(page)
    check("A52 暂停时在下面那条上拖，松手停在松手的位置、不播",
          not playing(page) and abs(t - target) < 0.3 and page.evaluate("idx") == j
          and page.inner_text("#stateTag") == "暂停中",
          f"松手处 {target:.2f} 秒，现在 {t:.2f} 秒，{page.inner_text('#stateTag')}")
    check("A56 拖完松手没有被当成点了一下（没跳回句首、没开始播）",
          not playing(page) and t - sentences[j]["start"] > 0.5, f"句首 {sentences[j]['start']:.2f} 秒")
    page.click("#playBtn")
    wait_playing(page)
    page.wait_for_timeout(300)
    t2 = now(page)
    tag = page.inner_text("#stateTag")
    page.click("#playBtn")
    check("A52b 松手后按播放，从松手的位置连续往下播", target - 0.1 <= t2 <= target + 1.2 and tag == "连续播放",
          f"按播放后 {t2:.2f} 秒，{tag}")

    # A53：连续播着拖，松手从落点接着连续播（过了那句的句末也不停）
    k = longest_in_shown({j})
    target = sentences[k]["end"] - 0.8
    page.click("#playBtn")
    wait_playing(page)
    press_and_drag(playhead_x(), x_of(target), y, release=False)
    paused_while_dragging = not playing(page)
    page.mouse.up()
    page.wait_for_timeout(300)
    t = now(page)
    started = playing(page) and target - 0.1 <= t <= target + 0.8
    page.wait_for_function(f"audio.currentTime > {sentences[k]['end'] + 0.3}", timeout=10000)
    check("A53 连续播着拖：拖的时候声音先停，松手从落点接着连续播，过了句末也不停",
          paused_while_dragging and started and playing(page) and page.inner_text("#stateTag") != "只播这一句",
          f"落点 {target:.2f} 秒，松手后 {t:.2f} 秒，句末 {sentences[k]['end']:.2f} 秒，现在 {now(page):.2f} 秒")
    page.click("#playBtn")

    # A54：只播一句时拖到别的句子，从落点播到那句句末停
    goto_body(page, 1)
    wait_playing(page)
    m = longest_in_shown({page.evaluate("idx"), j, k})
    target = sentences[m]["start"] + 0.3 * (sentences[m]["end"] - sentences[m]["start"])
    press_and_drag(playhead_x(), x_of(target), y)
    t = now(page)
    tag = page.inner_text("#stateTag")
    try:
        wait_paused(page)
        stopped = page.evaluate("window.__pauseAt")
    except Exception:  # noqa: BLE001  一直没停：判未通过，别让整个测试崩掉
        stopped = float("nan")
        page.click("#playBtn")
    check("A54 只播一句时拖到别的句子，从落点播到那句句末就停",
          target - 0.1 <= t <= target + 0.8 and tag == "只播这一句" and abs(stopped - sentences[m]["end"]) < 0.05,
          f"落点 {target:.2f} 秒，松手后 {t:.2f} 秒，停在 {stopped:.2f} 秒，句末 {sentences[m]['end']:.2f} 秒")

    # A57 / A58：圆点上方（条顶之外）也能按住拖；时间读数是「当前 / 这段总长」，拖着的时候跟着走
    goto_body(page, 5)
    wait_paused(page)
    n = longest_in_shown(set())
    target = sentences[n]["start"] + 0.5 * (sentences[n]["end"] - sentences[n]["start"])
    above = bar()["y"] - 10  # 条顶上方 10px：竖线圆点越出条外 6px，这里在圆点的上面
    press_and_drag(playhead_x(), x_of(target), above, release=False)
    page.wait_for_timeout(200)
    live = page.inner_text(".times").strip()
    page.mouse.up()
    page.wait_for_timeout(300)
    t = now(page)
    q = parts[page.evaluate("shownPart")]
    check("A57 竖线圆点的上方也能按住拖，松手停到拖到的地方",
          not playing(page) and abs(t - target) < 0.3 and page.evaluate("idx") == n,
          f"落点 {target:.2f} 秒，现在 {t:.2f} 秒")
    check("A58 时间读数写成「当前 / 这段总长」，拖着的时候跟着走",
          live == f"{clock_text(target - q['t0'])} / {clock_text(q['t1'] - q['t0'])}",
          f"拖着时读数是「{live}」，该是「{clock_text(target - q['t0'])} / {clock_text(q['t1'] - q['t0'])}」")


def update_part(page, shots: Path | None) -> None:
    """SPEC-008：页面上的「更新」和「这一页旧了」。会刷新页面，所以放在最后。
    接口 /api/version、/api/update 的回答在这里伪造（page.route）；真服务怎么停、怎么换版本在 tests/test_stable_copy.py。"""
    print("\n【换版本】")
    real = page.evaluate("myVersion")
    check("A30 没有新版本时看不到「更新」，也没有别的提示",
          page.is_hidden("#updateBtn") and page.is_hidden("#stale") and page.is_hidden("#updateFailed"),
          f"服务报的版本{'有' if real else '说不清'}")

    v1, v2 = "1a2b3c4d5e6f7a8b9c0d1a2b3c4d5e6f7a8b9c0d", "9f8e7d6c5b4a3f2e1d0c9f8e7d6c5b4a3f2e1d0c"
    what = "单词卡上多了例句的朗读"
    state = {"answer": {}, "down": False}

    def answer(version, waiting=False, failed=None):
        state["answer"] = {"version": version, "copy": "stable", "failed": failed,
                           "update": {"waiting": waiting, "what": what if waiting else ""}}

    def fake_version(route):
        if state["down"]:
            route.abort()
        else:
            route.fulfill(json=state["answer"])

    page.route("**/api/version", fake_version)
    page.route("**/api/update", lambda route: route.fulfill(status=202, json={"ok": True}))
    ask = "document.dispatchEvent(new Event('visibilitychange')); 0"   # 切回这个页签时页面会马上问一次

    def settle():
        page.evaluate(ask)
        page.wait_for_timeout(400)

    def reloaded():
        page.wait_for_function("window.__beforeReload === undefined && typeof lesson !== 'undefined' && lesson !== null "
                               "&& document.querySelectorAll('.seg').length > 0", timeout=15000)
        page.wait_for_timeout(500)

    def texts() -> str:
        return page.evaluate("document.body.innerText + ' ' + [...document.querySelectorAll('[title]')]"
                             ".map((e) => e.title).join(' ')")

    def shows(selector: str) -> bool:   # 等它出现，等不到判没出现（不让整个测试崩掉）
        try:
            page.wait_for_selector(selector, state="visible", timeout=3000)
            return True
        except Exception:  # noqa: BLE001
            return False

    answer(real, waiting=True)
    page.evaluate(ask)
    check("A32 页面开着时才钉的新版本，不刷新也会出现「更新」", shows("#updateBtn"))
    title = page.get_attribute("#updateBtn", "title") or ""
    check("A31 有新版本时「更新」出现，悬停写着这一版多了什么", what in title, title.replace("\n", " / "))
    check("A36 服务的版本没变，不挂「这一页旧了」", page.is_hidden("#stale"))

    answer(None)
    settle()
    no_version = page.is_hidden("#stale")
    state["down"] = True
    settle()
    state["down"] = False
    check("A37 服务说不清是哪一版、或者问不到（正在重启），都不挂「这一页旧了」",
          no_version and page.is_hidden("#stale"))

    answer(v2, waiting=True)
    page.evaluate(ask)
    check("A35 服务换了版本，这一页自己挂出「这一页旧了」", shows("#stale") and "还是旧的" in page.inner_text("#stale"),
          page.inner_text("#stale"))
    page.wait_for_timeout(700)  # 等淡入走完再截图
    shot(page, shots, "9-stale-and-update")
    seen = texts()

    answer(v2)
    goto_body(page, 20)
    wait_paused(page)
    where = page.inner_text("#counter")
    page.evaluate("window.__beforeReload = 1; 0")
    page.click("#staleRefresh")
    reloaded()
    check("A38 点「刷新」，页面刷新后回到原来那一句，提示没了",
          page.inner_text("#counter") == where and page.is_hidden("#stale"),
          f"{where} → {page.inner_text('#counter')}")

    sorry = "新版本没有换成，还是原来那一版，照常能用。告诉 claude，他来处理。"
    answer(v2, failed=sorry)
    settle()
    check("A34 上一次没换成，页面上有一句人话", page.is_visible("#updateFailed")
          and page.inner_text("#updateFailedText") == sorry, page.inner_text("#updateFailedText"))
    seen += texts()

    answer(v2, waiting=True)
    settle()
    goto_body(page, 30)
    wait_paused(page)
    where = page.inner_text("#counter")
    page.evaluate("window.__beforeReload = 1; 0")
    page.click("#updateBtn")
    page.wait_for_selector("#updating", state="visible", timeout=3000)
    shown = page.inner_text("#updating")
    page.wait_for_timeout(700)
    shot(page, shots, "10-updating")
    seen += texts()
    state["down"] = True                    # 服务停下、换版本
    page.wait_for_timeout(2500)
    answer(v1)                              # 起回来了，是新的一版
    state["down"] = False
    reloaded()
    check("A33 点「更新」出现「正在更新」，服务回来后页面自己刷新、停在原来那一句",
          "正在更新" in shown and page.inner_text("#counter") == where
          and page.is_hidden("#updating") and page.is_hidden("#updateBtn"),
          f"{where} → {page.inner_text('#counter')}")
    seen += texts()
    leaked = [v[:7] for v in (real, v1, v2) if v and v[:7] in seen]
    check("A39 屏幕上和悬停提示里都找不到版本号", not leaked, "、".join(leaked))
    page.unroute("**/api/version")
    page.unroute("**/api/update")


def sections_part(page, shots: Path | None, body: list[dict]) -> None:
    print("\n【分段】")
    sentences = page.evaluate("lesson.sentences")
    parts = page.evaluate("parts")
    nth = {p["n"]: (k, p) for k, p in enumerate(parts) if p["kind"] == "section"}
    check("A60 说话人、段标题、第几句合在卡片上方一行；整集分段条没有了",
          page.locator(".who #speaker, .who #partTitle, .who #counter").count() == 3
          and page.locator("#parts").count() == 0 and page.locator(".part").count() == 0,
          f"那一行：{page.inner_text('.who')[:50]}")

    k2, p2 = nth[2]
    page.evaluate(f"playOne({p2['first'] + 2})")
    page.wait_for_timeout(200)
    segs = page.evaluate("[...document.querySelectorAll('.seg')].map((e) => Number(e.dataset.i))")
    check("A60b 跳到别的段，这一行和下面那条都跟着换",
          segs == list(range(p2["first"], p2["last"] + 1))
          and page.inner_text("#counter").startswith("第 2 段")
          and page.inner_text("#partTitle").strip("· ") == p2["title"],
          f"{page.inner_text('#counter')}，{len(segs)} 小段")

    _, p1 = nth[1]
    page.evaluate(f"playFrom({p1['last'] - 1})")
    wait_paused(page, timeout=15000)
    stopped = page.evaluate("window.__pauseAt")
    end1 = sentences[p1["last"]]["end"]
    check("A25 连续播放到一段的末尾自动停", abs(stopped - end1) < 0.04,
          f"停在 {stopped:.3f} 秒，这段结束在 {end1:.3f} 秒")
    check("A25b 停之前音量渐弱到零", page.evaluate("window.__gainAtPause") < 0.05)
    check("A25c 卡片上换成「这段再听一遍」「听下一段」",
          page.is_visible("#sectionEnd") and page.inner_text("#endTitle") == "第 1 段听完了"
          and page.is_hidden("#textBtn"), page.inner_text("#endTitle"))
    check("A25d 播放键写着「下一段」", page.inner_text("#playLabel") == "下一段", page.inner_text("#playLabel"))
    page.wait_for_timeout(500)  # 等淡入动画走完再截图
    shot(page, shots, "4-section-end")
    page.click("#againSectionBtn")
    page.wait_for_timeout(300)
    check("A26 按「这段再听一遍」，回到这段开头", in_sentence(now(page), sentences[p1["first"]]),
          f"现在 {now(page):.2f} 秒")

    page.evaluate(f"playFrom({p1['last']})")
    wait_paused(page, timeout=15000)
    page.keyboard.press(" ")
    page.wait_for_timeout(300)
    check("A27 段末按空格，从下一段开头播",
          playing(page) and in_sentence(now(page), sentences[p2["first"]])
          and page.inner_text("#counter").startswith("第 2 段"),
          f"现在 {now(page):.2f} 秒，{page.inner_text('#counter')}")

    page.evaluate(f"playOne({p1['last']})")
    wait_paused(page, timeout=15000)
    check("A25e 一句一句听到段末最后一句，不换成「这段听完了」，看文字按钮还在",
          page.is_hidden("#sectionEnd") and page.is_visible("#textBtn")
          and page.inner_text("#stateTag") == "停在这句末尾", page.inner_text("#stateTag"))

    _, plast = nth[max(nth)]
    page.evaluate(f"playFrom({plast['last']})")
    wait_paused(page, timeout=15000)
    check("A28 最后一段播完写「这集听完了」，按钮是「从第 1 段开始」",
          page.inner_text("#endTitle") == "这集听完了"
          and page.inner_text("#nextSectionBtn").startswith("从第 1 段开始"),
          f"{page.inner_text('#endTitle')} / {page.inner_text('#nextSectionBtn')}")

    if parts[0]["kind"] == "intro":
        last_intro = parts[0]["last"]
        page.evaluate(f"idx = {last_intro}; start(lesson.sentences[{last_intro}].end - 0.4); render()")
        page.wait_for_function(f"audio.currentTime > {body[0]['start'] + 0.3}", timeout=15000)
        check("A29 片头播完不停，直接进正文第 1 段",
              playing(page) and page.inner_text("#counter").startswith("第 1 段"), page.inner_text("#counter"))
        page.click("#playBtn")


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
        return 1
    # 全过：记下这次测的是哪份代码。钉版本送给 owner 之前要核对它（SPEC-008 R4）
    stable_copy.record_test_pass(Path(__file__).resolve().parent.parent, len(passes))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
