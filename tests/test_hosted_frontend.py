"""资料库侧边栏和上传面板的自动检查（SPEC-009 R8）——Playwright 真的打开对外模式的页面、真的点。

用假备课命令（prep_command 注入，同 tests/test_hosted_prep.py）跑完整条用户路：
注册（邀请码）→ 空库待机 → 上传（选错文件的人话提示）→ 未备课材料（备课／删除）→
备课中（转圈＋已用时）→ 变课的那一刻（材料区消失、课区高亮、顶部通知）→ 点课切换 →
进度点 → 失败重试 → 登出。不连网、不烧识别和模型的钱；音频和课都是假字节。

跑法：<pywork python> tests/test_hosted_frontend.py   （约 20 秒；账号、备课台全在临时目录，跑完就删）
"""

import json
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import serve as serve_mod  # noqa: E402

failures: list[str] = []
passes: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (passes if ok else failures).append(name)
    print(f"  {'通过' if ok else '未通过'}　{name}" + (f"　{detail}" if detail else ""))


# 假备课命令：收到（课名, 材料台, 课台），从 meta.json 读标题写一份假课；讲稿里带 FAIL 就失败。
tmp = Path(tempfile.mkdtemp(prefix="lm-front-"))
fake = tmp / "fake_prep.py"
fake.write_text("""
import json, sys, time
from pathlib import Path
ke, mr, lr = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
meta_path = mr / ke / "meta.json"
if not meta_path.exists():
    sys.exit(4)  # 备课台必须带 meta.json：teach.py 要从里面读标题和来源（SPEC-002 R9）
time.sleep(0.8)  # 让「备课中」在页面上待一会儿，轮询看得到
t = mr / ke / "transcript.txt"
if t.exists() and "FAIL" in t.read_text(encoding="utf-8"):
    sys.exit(3)
meta = json.loads(meta_path.read_text(encoding="utf-8"))
ld = lr / ke
ld.mkdir(parents=True, exist_ok=True)
(ld / "lesson.json").write_text(json.dumps({
    "title": meta.get("title") or ke, "source": meta.get("source") or "",
    "sections": [{"first": 0, "last": 1, "title": "一段"}],
    "sentences": [
        {"id": 0, "start": 0, "end": 2.0, "text": "Hi there.", "zh": "你好。", "speaker": "Georgie"},
        {"id": 1, "start": 2.0, "end": 4.0, "text": "Hello.", "zh": "你好。", "speaker": "Neil"},
    ],
}, ensure_ascii=False), encoding="utf-8")
(ld / "audio.m4a").write_bytes(b"FAKE_M4A")
""", encoding="utf-8")

server = serve_mod.make_server(port=0, hosted_config={
    "invite": "测试邀请码", "data_dir": tmp / "data", "secure_cookie": False,
    "prep_command": [sys.executable, str(fake)],
    "materials_root": tmp / "stage_materials", "lessons_root": tmp / "stage_lessons",
})
threading.Thread(target=server.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{server.server_address[1]}"
EMAIL = "f@example.com"


def upload_through_panel(page, name, title="", source="", script=""):
    """走上传面板传一份材料（点按钮、选音频、可选讲稿文件、填字段、点上传），返回材料号。
    入口哪个活着用哪个：侧边栏开着的「＋上传材料」、空库卡片上的「上传一集」。"""
    page.click("#uploadBtn" if page.is_visible("#uploadBtn") else "#emptyAct")
    page.set_input_files("#audioInput", {"name": name, "mimeType": "audio/mpeg",
                                         "buffer": b"FAKE_AUDIO_BYTES_" * 40})
    if title:
        page.fill("#upTitle", title)
    if source:
        page.fill("#upSource", source)
    if script:
        page.set_input_files("#scriptInput", {"name": "script.txt", "mimeType": "text/plain",
                                              "buffer": script.encode("utf-8")})
    page.click("#uploadSend")
    page.wait_for_selector("#libMaterialList .lib-row.mat")
    lib = page.evaluate("fetch('/api/library').then((r) => r.json())")
    return lib["materials"][0]["id"]


def run(page) -> None:
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    print("\n【注册进站：空库待机】")
    page.goto(BASE + "/")
    page.wait_for_selector("#f")
    check("没登录开站，落在登录页", page.url.rstrip("/") == BASE and page.is_visible("#f"), page.url)
    page.click("#tab-reg")
    page.fill('input[name="email"]', EMAIL)
    page.fill('input[name="password"]', "passwd123")
    page.fill('input[name="invite"]', "测试邀请码")
    page.click("#submit")
    page.wait_for_url(f"{BASE}/web/")
    page.wait_for_selector("#emptyHint")
    check("新账号直接进播放器（不挡路）：卡片里一句邀请，播放控制收起",
          page.inner_text("#emptyTitle") == "资料库还是空的"
          and page.is_hidden(".who") and page.is_hidden(".deck") and page.is_hidden("#cardActions"),
          page.inner_text("#emptyTitle"))
    check("空库的行动按钮就是「上传一集」，左上角资料库入口在、侧边栏收着",
          page.inner_text("#emptyAct") == "上传一集" and page.is_visible("#libBtn") and page.is_hidden("#libPanel"))

    print("\n【上传面板】")
    page.click("#emptyAct")   # 空卡片上的按钮开的就是上传面板
    page.wait_for_selector("#uploadPanel:not([hidden])")
    page.click("#uploadSend")    # 没选音频
    check("没选音频就点上传，一句人话", page.is_visible("#uploadErr")
          and "先选" in page.inner_text("#uploadErr"), page.inner_text("#uploadErr"))
    page.set_input_files("#audioInput", {"name": "virus.exe", "mimeType": "application/octet-stream",
                                         "buffer": b"MZ"})
    check("选的不是 mp3，拖放区就地说明白", "只收 mp3" in page.inner_text("#dropZone"),
          page.inner_text("#dzTitle"))
    page.set_input_files("#scriptInput", {"name": "readme.docx", "mimeType": "application/octet-stream",
                                          "buffer": b"x" * 10})
    check("讲稿选错类型，一句人话", "TXT" in page.inner_text("#scriptName"))
    page.click("#uploadClose")
    mid1 = upload_through_panel(page, "coffee.mp3", title="平时怎么喝咖啡",
                                source="Real Easy English", script="Georgie: Hello\nNeil: Hi")
    check("传完落到材料区（侧边栏自动打开）：标题＋备课＋删除，状态未备课",
          page.is_visible("#libPanel")
          and "平时怎么喝咖啡" in page.inner_text("#libMaterialList")
          and "备课" in page.inner_text("#libMaterialList")
          and page.locator("#libMaterialList .x-btn").count() == 1)

    print("\n【备课：备课中 → 变课的那一刻】")
    row = page.locator("#libMaterialList .lib-row").filter(has_text="平时怎么喝咖啡")
    row.locator(".mini-btn").click()
    page.wait_for_selector("#libMaterialList .lib-row.prepping .spin")
    check("点备课，这行变「备课中」（转圈＋已用时）",
          "备课中" in page.inner_text("#libMaterialList")
          and re.match(r"\d+:\d\d", page.inner_text("#libMaterialList .lib-elapsed")) is not None,
          page.inner_text("#libMaterialList .lib-sub"))
    lesson = page.locator("#libLessonList .lib-row.lesson").filter(has_text="平时怎么喝咖啡")
    lesson.wait_for(state="visible", timeout=10000)   # 假备课 0.8 秒，轮询 2.5 秒一眼
    check("材料变课：材料区不再有它、课区出现（按系列分组）、高亮一下",
          page.locator("#libMaterialList .lib-row").count() == 0
          and "fresh" in (lesson.get_attribute("class") or "")
          and page.inner_text("#libLessonList .lib-group") == "Real Easy English",
          page.get_attribute("#libLessonList .lib-row.lesson", "class") or "")
    grad = page.locator(".notice").filter(has_text="备好了")
    check("顶部说一声「备好了」、给「去听」",
          grad.count() == 1 and grad.locator(".notice-btn").inner_text() == "去听")
    check("页面没有报错", not errors, "; ".join(errors[:2]))

    print("\n【点课切换】")
    lesson.click()
    page.wait_for_url(f"{BASE}/web/?lesson={mid1}")
    page.wait_for_function("document.getElementById('title').textContent !== '听力练习'")
    check("点了停在句首待命、标题和来源是备课时读的（meta.json）",
          page.inner_text("#title") == "平时怎么喝咖啡" and page.inner_text("#source") == "Real Easy English"
          and page.inner_text("#speaker") == "Georgie" and page.evaluate("audio.paused") is True,
          f"{page.inner_text('#title')} / {page.inner_text('#source')}")
    check("选了集侧边栏自动收起", page.is_hidden("#libPanel") and page.is_hidden("#libMask"))
    page.reload()
    page.wait_for_function("document.getElementById('title').textContent !== '听力练习'")
    check("收起的选择记住了（刷新不再自动展开）", page.is_hidden("#libPanel"))
    page.click("#libBtn")
    check("正在听的这集高亮、带小声浪，进度点空心（没开始）",
          "current" in (page.get_attribute("#libLessonList .lib-row.lesson", "class") or "")
          and page.locator("#libLessonList .now-bars").count() == 1
          and not re.search(r"half|full", page.evaluate("document.querySelector('#libLessonList .dot').className")))
    page.evaluate(f"localStorage.setItem('listening:{mid1}:done', '1'); 0")
    page.click("#libClose")
    page.click("#libBtn")
    page.wait_for_selector("#libLessonList .dot.full", timeout=5000)   # 打开时轮询重画，等它画完
    check("整集听过的画实心点", True)

    print("\n【没讲稿的材料：就地补传、删除】")
    mid2 = upload_through_panel(page, "news.mp3")
    row = page.locator("#libMaterialList .lib-row").filter(has_text="news")
    check("没传讲稿的材料有一个就地补传的口（＋讲稿），不说「必须」",
          row.locator(".mini-btn", has_text="＋讲稿").count() == 1 and "必须" not in row.inner_text())
    page.on("dialog", lambda d: d.accept())
    row.locator(".x-btn").click()
    page.wait_for_function("document.querySelectorAll('#libMaterialList .lib-row').length === 0")
    check("删除（确认一下）后材料区空了", True)

    print("\n【失败 → 补讲稿 → 重试】")
    mid3 = upload_through_panel(page, "bad.mp3", title="坏材料", script="FAIL")
    page.locator("#libMaterialList .lib-row").filter(has_text="坏材料").locator(".mini-btn", has_text="备课").click()
    failed = page.locator("#libMaterialList .lib-row.failed")
    failed.wait_for(state="visible", timeout=10000)
    check("失败停在那、一句人话原因、能重试", "备课没成功" in failed.locator(".lib-sub").inner_text()
          and failed.locator(".mini-btn", has_text="重试").count() == 1, failed.locator(".lib-sub").inner_text())
    with page.expect_response(lambda r: "/api/material/script" in r.url) as got_script:   # 钉住补讲稿的请求
        failed.locator(".mini-btn", has_text="＋讲稿").click()   # 失败行上补一份好讲稿
        page.set_input_files("#rowScriptInput", {"name": "fixed.txt", "mimeType": "text/plain",
                                                 "buffer": "Georgie: Fixed.".encode("utf-8")})
    check("失败行上补传讲稿（TXT 文件）", got_script.value.ok)
    page.locator("#libMaterialList .lib-row").filter(has_text="坏材料").locator(
        ".mini-btn", has_text="重试").click()
    page.locator("#libLessonList .lib-row.lesson").filter(has_text="坏材料").wait_for(state="visible", timeout=10000)
    check("补完讲稿重试，成了课（资料库两节课）",
          page.locator("#libLessonList .lib-row.lesson").count() == 2)

    print("\n【登出、登录页】")
    if not page.is_visible("#logoutBtn"):   # 侧边栏收着才需要点 ☰ 开（开着时面板盖住 ☰，用面板里的按钮）
        page.click("#libBtn")
    page.click("#logoutBtn")
    page.wait_for_url(f"{BASE}/login")
    check("登出回到登录页", page.is_visible("#f"))
    check("登录只要邮箱密码（邀请码只在注册时问），邮箱已经填好、只差密码",
          page.is_hidden("#row-invite") and page.input_value('input[name="email"]') == EMAIL
          and page.evaluate("document.activeElement === document.querySelector('input[name=password]')"))
    check("全程页面没有报错", not errors, "; ".join(errors[:2]))


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        try:
            run(page)
        finally:
            browser.close()
            server.shutdown()
            server.server_close()
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n通过 {len(passes)} 项，未通过 {len(failures)} 项")
    if failures:
        print("未通过：" + "、".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
