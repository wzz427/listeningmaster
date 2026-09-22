# CLAUDE.md

> 进这个仓库的第一读物。只装等不到动手那一刻才送到的东西；细则住各自文档。100 行以内。
> 规矩全文见《AI 编程项目管理指南》`guide.md`（在桌面，不在本仓库）。

## 这个项目

- 一句话：给听力偏弱的孩子做一个按句子播放的英语听力工具，听不懂能跳回本句重听、按需看文字、点词查义和听发音。
- 首要用户：owner 的孩子，刚过剑桥 PET（B1），听力在及格线附近。其次是几位熟人家长的孩子。
- 需求总源：`demand.md`；阶段：起步。

## 第一条

用第一性原理思考。目标不清 → 停下来讨论；路不是最短 → 说出来；都清楚 → 一口气做完。停的是目标不清，不停的是活干到一半。

## 怎么想（指南第二章）

共同责任人，对齐理由不是措辞 · 不逢迎 · 抽象词不当判据 · 找根因戴科学家帽 · 不靠猜先查 · 关键环节先实验 · 改共用的东西不打补丁 · 边际效益低的不干，但用户能感觉到的 bug 一律修。

## 怎么说话（指南第三章、附录 B）

说人话，内部编号和自造词不许出现 · 他的话分拍板 / 待议 / 顾虑 · 工程细节自己拍，产品方向必问 · 收尾落到做什么 · 归谁 · 多久 · 一条消息一件事。

## 红线

| 红线 | 规则 |
|---|---|
| 密钥不入仓库、不流向输出 | `api-keys.txt` 已在 `.gitignore` 第一行。读取只能在程序里读，不许打印、不许写进日志和报错、不许出现在命令行参数里；「看看有哪些键名」也不行 |
| 对外动作要 owner 同意 | 部署、分享给其他家长；发起权在他 |
| 全套测试要批准 | 相关那份随时跑；全套攒一批申请 |
| 语言 | 正式文字中文；旁白只英文；禁止日语；标识符和文件名英文 |
| 素材版权 | BBC 素材只在家庭和熟人之间非商业使用，不公开传播、不上传到公开可访问的地址 |
| 孩子看到的内容 | 大模型生成的释义和题目，owner 审过才给孩子用 |

## 环境与命令

- Python：`C:\Users\wzzpk\.conda\envs\pywork\python.exe`（conda 环境 pywork，不在 PATH 上，用绝对路径调用；装包用 `<该路径> -m pip install`）。不要用系统 Python，也不要另建环境。
- 机器：Windows 11，显卡 RTX 500 Ada（4GB 显存）。
- 测试：`<pywork python> tests/test_player.py`——用 Playwright 真的开浏览器、真的点按钮、真的看音频播到第几秒，52 项，不到 1 分钟。**改完播放器必须跑**。加 `--show` 能看见浏览器窗口，加 `--shots <目录>` 存截图看界面。Playwright 和 chromium 已经装在 pywork 里。
- 验声音：`<pywork python> tests/test_audio.py`——录下真的 Chrome 放出来的每一句，交给机器耳朵听开头结尾对不对，做一页试听给人耳抽查，约 5 分钟、几分钱。**改了句子边界或播放器的停法就跑**。只核对数字发现不了声音问题（`docs/lessons.md` 2026-09-22）。
- 启动播放器：双击 `start-player.bat`，或跑 `<pywork python> pipeline/serve.py 8765`，再打开 http://localhost:8765/web/ 。**不要用 `python -m http.server`**：它不支持从文件中间取一段，音频跳不动（见 `docs/lessons.md`）。
- 备课（一集跑一次，依次）：`pipeline/audio.py` 转音频 → `pipeline/asr_probe.py` 识别 → `pipeline/align.py` 对齐讲稿 → `pipeline/refine_bounds.py` 按音量精修句子边界 → `pipeline/ear_bounds.py` 机器耳朵复查句子开头结尾 → `pipeline/teach.py` 生成中文、按话题分段（默认复用上一版已有的中文和分段，`--fresh` 全部重来，`--resplit` 只重切分段）。

## 干这件事进哪

| 干什么 | 进哪 |
|---|---|
| 接下来动哪件 / 销账 / 开新活 | `docs/debts.md` |
| 接手 / 上一段为什么这么改 | `docs/handoff.md` |
| 撞报错 | `docs/lessons.md` |
| 为什么这么选 | `docs/decisions.md` |
| 接需求 / 写规格 | `demand.md` → `specs/`（先对话再写） |
| 竞品和听力教学研究怎么说 | `docs/research.md` |
| 调百炼语音识别 | `docs/refs/qwen-asr-api.md`（官方文档存档） |
| 原始素材 | `materials/<期号>/`（音频 + 讲稿 + 练习） |
| 备课程序 | `pipeline/` |
| 播放器 | `web/`（三个文件：index.html、style.css、app.js） |
| 验播放器改得对不对 | `tests/test_player.py` |
| 改界面 | 先加载 frontend-design 技能（owner 2026-09-21 要求按真正的前端设计标准做）；改完跑 `tests/test_player.py --shots <目录>` 看截图 |
| 量句子边界干不干净 | 先听：`tests/test_audio.py`；再量：`pipeline/measure_bounds.py`（只看音量，会被骗） |
| 压缩上下文 | `/warp` |

## 节奏

每有进展：动欠账表 · 交接页加一行 · 提交（多会话带文件列表）。开机：本文 → 欠账表「现在就能动手」→ 交接页「现在在哪」。主线：owner 的新功能 > 清 bug > 自己找 bug。
