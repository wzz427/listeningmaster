# 技术架构

> 答什么：这个软件由哪几块拼成、数据怎么从一份音频流到孩子的屏幕、每个文件是干什么的、调了哪些外部服务、密钥在哪。要做什么、为什么这么做住 `specs/`，这里只画「现在长什么样」。
> 谁何时读：接手时读一遍；加文件、改文件格式、接新的外部服务、上服务器之前。改完代码顺手改这里，再跑 `tests/test_docs.py`：这里写到的文件不存在、代码文件这里没写到、课程文件的字段对不上，它都会报错。
> 怎么变短：只写现在的结构；换掉的写一句进 `docs/decisions.md`，这里删掉。

## 一张图

```
  materials/<课>/                     仓库外：WordsAudio/（发音词典，5 万词的谷歌英音）
  音频 mp3 + 讲稿 PDF                          │ 备课时拷这集用到的词
        │                                      ▼
        │  备课：pipeline/ 里六个程序依次跑（SPEC-002）
        │  ── 百炼：录音文件识别、临时存储、机器耳朵
        │  ── DeepSeek：每句中文、生词、每个词的那一行、分段
        ▼
  lessons/<课>/  lesson.json · audio.m4a · tts/ · 报告
        │
        │  本地服务 pipeline/serve.py（只听本机 127.0.0.1）
        │  ── 静态文件，支持从文件中间取一段（音频才跳得动）
        │  ── /api/explain、/api/more：点词补查、展开（带着密钥问 DeepSeek）
        │  ── /api/speak：词组和词典里没有的词现读（带着密钥问百炼 Emily）
        ▼
  web/ 播放器（浏览器里，三个文件，没有构建步骤）
        学习记录存在浏览器本地，能导出
```

模块之间只通过文件交接：备课写文件，播放器读文件；播放器唯一连出去的是本地服务。

## 目录

| 位置 | 干什么 | 规格 |
|---|---|---|
| `demand.md` | owner 的需求原话、优先级、不做什么、约束 | — |
| `AGENTS.md` | ZCode 自动读到的入口：指针、开机三步、红线摘录；第一读物仍是 `CLAUDE.md`（决策 D36） | — |
| `idea.txt` | owner 起步时写的最初想法，只作历史 | — |
| `specs/` | 规格：`SPEC-000-overview.md` 是总需求和模块表，其余一块一份；`SPEC-template.md` 是空模板 | — |
| `docs/` | 本文、`workflow.md`（开发流程和验证）、`environment.md`（开发环境和工具）、`decisions.md`、`lessons.md`、`debts.md`、`handoff.md`、`listening-led-course.md`（课程方案：理念、一集六步、单元阶段）；`research/` 放调研产出——`2026-09-12-products-teaching-tech-survey.md` 是三轮调研摘要（产品、教学研究、技术），报告一篇一文件、文件名带日期前缀（D46）；`refs/qwen-asr-api.md` 是百炼识别的官方文档存档；`history/` 放整批搬走的旧交接记录 | — |
| `materials/<课>/` | 原始素材：音频、讲稿、练习 | SPEC-002 |
| `lessons/<课>/` | 备好的一集，见下面「每一集的文件」 | SPEC-002 |
| `pipeline/audio.py` | 转音频：16k 单声道 wav（识别、量音量用）、m4a（播放器用）；用 imageio-ffmpeg 自带的 ffmpeg | SPEC-002 |
| `pipeline/asr_probe.py` | 上传临时存储、调百炼录音文件识别，存 `asr_raw.json` | SPEC-003 |
| `pipeline/transcript.py` | 从 BBC 讲稿 PDF 读出「谁说了什么」 | SPEC-003 |
| `pipeline/align.py` | 识别结果对齐讲稿、说话人、片头片尾、切句，写 `timeline.json`、`align_report.md` | SPEC-003 |
| `pipeline/refine_bounds.py` | 按音量精修句子起止，写 `bounds_report.md` | SPEC-004 |
| `pipeline/ear.py` | 机器耳朵：一段声音交给百炼 `qwen3-asr-flash` 听出是哪些词，带限流重试 | SPEC-004 |
| `pipeline/ear_bounds.py` | 机器耳朵查每句开头结尾、往外挪，最后照 `bounds_manual.json` 改，写 `ear_report.md` | SPEC-004 |
| `pipeline/measure_bounds.py` | 只看音量量句子边界干不干净，比较改边界前后 | SPEC-004 |
| `pipeline/teach.py` | 备课最后一步：每句中文、挑生词、调 `explain.prepare` 写那一行、分段、调 `tts.build` 拷朗读，写 `lesson.json`、`teach_raw.json` | SPEC-005 |
| `pipeline/explain.py` | 单词卡的内容：备课时整句写那一行；点词时补查、展开、词组现读；缓存 | SPEC-006 |
| `pipeline/tts.py` | 发音词典（建、查、拷进课程文件夹）、百炼 Emily 合成、抽听页 | SPEC-007 |
| `pipeline/tts_check.html` | `tts.py check` 用的抽听页模板 | SPEC-007 |
| `pipeline/llm.py` | 调大模型的统一口：deepseek 开头走 DeepSeek，qwen 开头走百炼兼容接口；关掉 deepseek 的思考模式 | SPEC-000 R5 |
| `pipeline/keys.py` | 从 `api-keys.txt` 读密钥，只读进内存 | SPEC-000 R2 |
| `pipeline/serve.py` | 本地服务，见下面「本地服务」；`--hosted` 起对外模式（SPEC-009）：会话挡全站、注册/登录/登出、上传/资料库/删材料、备课任务（串行队列跑 SPEC-002 的六步，或配置 `prep_command` 换假命令测试） | SPEC-001 R12、SPEC-009 |
| `pipeline/accounts.py` | 邮箱账号（对外版地基）：注册要邀请码、登录发会话、连错锁、密码只存 PBKDF2 哈希；数据住 `server-data/`（不进 git），布局 `server-data/<账号id>/{materials/<材料id>/{audio.*, script.txt, meta.json}, lessons/<课>/}`——材料 meta.json 的 state 就是 SPEC-009 的状态机（new/prepping/done/failed） | SPEC-009 |
| `pipeline/stable_copy.py` | 体验版和开发版：建体验版、钉版本、换版本（失败退回、留下孩子用出来的数据）、退回上一版、双击后起服务的循环；见下面「两份代码」 | SPEC-008 |
| `pipeline/compare_models.py` | 一次性：比较两个模型写的中文和生词判断，出 `model_compare.md` | SPEC-005 |
| `web/index.html`、`web/style.css`、`web/app.js` | 播放器，见下面「播放器」 | SPEC-001 |
| `web/login.html` | 登录页（对外模式专用）：注册（要邀请码）／登录，注册成功即登录；自包含样式，不依赖 style.css | SPEC-009 |
| `web/fonts/` | 放在本地的字体：Literata（英文正文）、DM Mono（数字）、Noto Serif 裁出来的音标字体，各带许可证 | SPEC-001 R22、SPEC-006 R8 |
| `tests/test_player.py` | 播放器的自动检查（Playwright），编号对应各规格的 A 编号 | `docs/workflow.md` |
| `tests/test_audio.py` | 验声音：录下真的 Chrome 放出来的声音，对时间、机器耳朵听、出试听页 | SPEC-004 R7 |
| `tests/test_docs.py` | 文档和代码对不对得上 | `docs/workflow.md` |
| `tests/test_accounts.py` | 账号模块的单元检查（注册、登录、会话、连错锁、密码不落盘），临时目录里跑 | SPEC-009 |
| `tests/test_hosted_server.py` | 对外模式的自动检查：真起服务真发请求——挡站、注册登录登出、noindex、限流、无「更新」接口 | SPEC-009 |
| `tests/test_hosted_upload.py` | 上传、资料库、删材料的自动检查：真上传假音频字节——类型和大小闸、标题讲稿落盘、两账号隔离、课路径按账号指路 | SPEC-009 |
| `tests/test_hosted_prep.py` | 备课任务的自动检查：假备课命令跑通状态机（排队、备课中挡重复点、成功变课、失败人话原因、重试） | SPEC-009 |
| `tests/test_stable_copy.py` | 换版本的自动检查：临时目录里造真的仓库和体验版，真的切版本、真的起服务 | SPEC-008 |
| `start-player.bat` | 双击：旁边有体验版就转去体验版，然后调 `pipeline/stable_copy.py run` 起服务、打开浏览器。只放英文字符 | SPEC-008 R2 |
| `.zcode/commands/wrap.md` | 收尾命令 `/wrap`：压缩上下文之前把只活在对话里的东西写到盘上、扫文档、提交 | — |
| `api-keys.txt` | 密钥，不进仓库（`.gitignore` 第一行） | SPEC-000 R2 |

## 每一集的文件（`lessons/<课>/`）

| 文件 | 谁写 | 谁读 | 进仓库 |
|---|---|---|---|
| `audio_16k.wav` | `asr_probe.py`（没有时 `refine_bounds.py` 补） | 精修、机器耳朵 | 不进，随时能重转 |
| `audio.m4a` | `audio.py` | 播放器 | 进 |
| `asr_raw.json` | `asr_probe.py` | `align.py` | 进（识别要花钱，留着原样） |
| `timeline.json` | `align.py`，`refine_bounds.py`、`ear_bounds.py` 原地改起止 | `teach.py` | 进 |
| `align_report.md`、`bounds_report.md`、`ear_report.md` | 第 3、4、5 步 | 人 | 进 |
| `bounds_manual.json` | 人（owner 听过定的） | `ear_bounds.py` | 进 |
| `lesson.json` | `teach.py` | 播放器、`explain.py`、`tts.py check` | 进 |
| `teach_raw.json` | `teach.py` | 人 | 进 |
| `explain_cache.json` | 本地服务（点词补查、展开） | 本地服务 | 进（查过的不再花钱） |
| `tts/google_en-GB/` | `teach.py` 从发音词典拷 | 播放器 | 进 |
| `tts/bailian_emily/` | 本地服务（词组、词典里没有的词现读） | 播放器 | 进 |
| `model_compare.md` | `compare_models.py` | 人 | 进 |
| `audio_check/`、`tts_check/` | `tests/test_audio.py`、`tts.py check` | 人 | 不进，随时能重新生成 |
| `tts_try/`、`tts_compare/`、`bounds_try/` | 一次性对比页（选声音、选边界时做的） | 人 | 不进 |

## 课程文件 `lesson.json`

播放器只认这一份。字段（`tests/test_docs.py` 会拿第一集的文件核对下表每个字段都在）：

| 字段 | 是什么 |
|---|---|
| `lesson` | 课名，和文件夹同名 |
| `title`、`source` | 标题、出处（现在写死在 `teach.py` 里，SPEC-002 R9） |
| `audio` | 播放器放的音频文件名 |
| `bodyStart` | 正文第一句的开始秒数 |
| `sections[].first`、`sections[].last`、`sections[].title` | 每段的第一句、最后一句的编号和中文小标题（SPEC-005） |
| `sentences[].id`、`sentences[].speaker`、`sentences[].start`、`sentences[].end`、`sentences[].text`、`sentences[].zh` | 每句：编号、说话人（片头片尾写「片头片尾」）、起止秒数、英文原话、中文 |
| `sentences[].words[].text`、`sentences[].words[].start`、`sentences[].words[].end`、`sentences[].words[].key` | 每个词：原样的写法、识别给的起止（只用来高亮正在读的词）、查朗读和生词用的小写形式 |
| `sentences[].notes[].words`、`sentences[].notes[].text`、`sentences[].notes[].pos`、`sentences[].notes[].ipa`、`sentences[].notes[].zh`、`sentences[].notes[].more` | 每个词的那一行（SPEC-006）：管这句里哪几个词（词组是几个）、词或词组、词性、音标、意思、给不给展开 |
| `glossary.*.hard` | 这一集每个词（小写形式）是不是生词（SPEC-005） |
| `tts.voice`、`tts.files` | 朗读用的是谁的声音；词 → 朗读文件（相对课程文件夹） |

## 本地服务（`pipeline/serve.py`）

- 只听本机 127.0.0.1，默认端口 8765；网页地址 http://localhost:8765/web/ ，`?lesson=<课>` 选哪一集（默认 260821）。
- 静态文件：支持 Range（从文件中间取一段），不然音频跳不到指定的秒数；一律不缓存，改了代码刷新就生效。`python -m http.server` 不支持 Range，不能用（`docs/lessons.md` 2026-09-12）。
- 接口，请求都是 JSON，都带 `lesson`；课名只许字母数字、下划线、连字符，防止借路径读别的文件：
  - `POST /api/explain` `{sentence, word}` → 那一行：先查缓存，再查 `lesson.json` 里备课写好的，都没有才问模型。
  - `POST /api/more` `{sentence, word}` → 展开的内容，查过的存进缓存。
  - `POST /api/speak` `{key, text}` → `{file}`：词组或词典里没有的词的朗读文件，没有就让 Emily 现读、存下来。
  - 出错只回 `{"error": 错误的种类}`，不回详情：详情里可能带着请求头（SPEC-000 R2）。
- 换版本的两个接口（SPEC-008），不带 `lesson`：
  - `GET /api/version` → `{version, copy, update: {waiting, what}, failed}`：服务起来时是哪个提交（页面拿它判断自己旧没旧，不显示）、是体验版还是开发版、有没有一版等 owner 点「更新」和那一版多了什么、上一次没换成的那句话。钉住的是哪个提交不给。
  - `POST /api/update` → 202 后服务以退出码 7 停下；没有要换的、或者服务不是 `--managed` 起的，回 409。
- 命令行：`serve.py [端口] [--open] [--managed]`。`--open` 起来后打开浏览器；`--managed` 表示有 `stable_copy.py run` 负责换完版本把它拉起来。开发版旁边有体验版时，开发版拿 8765 当场拒绝。
- 独占端口：Python 自带的 HTTPServer 在 Windows 上允许两个服务同时占一个端口，这里关掉了（`docs/lessons.md` 2026-09-24）。

## 播放器（`web/`）

- 三个文件，纯 HTML + JavaScript + CSS，不用框架、没有构建步骤（决策 D14）。
- `app.js` 按功能分块，块头有注释：启动、分段、声音（渐强渐弱、准点停）、跳句（两种播法）、画面、进度条、单词、全文、按钮和键盘。开头写着几条要记住的理由。
- 声音走 Web Audio 的音量节点，停之前在上面做渐弱（SPEC-001 R16）；验声音时在同一个节点后面接录音（`tests/test_audio.py`）。
- 学习记录和设置存在浏览器本地（`localStorage`，按课名分开），「导出」存成文件（决策 D9）。
- 字体全在 `web/fonts/`，中文用系统字体（决策 D19）。
- 换版本（SPEC-008）：每分钟、切回页签时问一次 `/api/version`；服务换了版本挂「这一页旧了」；有钉住的版本才出现「更新」。刷新前把当前句子记在 `sessionStorage`，刷新后回到这一句。

## 两份代码（SPEC-008）

- 开发版：这个仓库目录，claude 改。体验版：旁边的 `WorkSpace\ListeningMaster-stable`，这个仓库的第二个工作目录（`git worktree`，不挂分支），owner 和孩子用，一个字不手改。两份共用一个 git 仓库，体验版能切到开发版里的任何提交。
- 双击任何一份里的 `start-player.bat`，起的都是体验版，地址 http://localhost:8765/web/ 。
- 新版本怎么过去：claude `stable_copy.py invite` 钉一版（要求 `tests/test_player.py` 对这份代码全过，它全过时把代码指纹记在开发版根上的 `.player-tests-passed.json`）→ 钉的记录写在体验版根上的 `.stable-invite.json` → 页面出现「更新」→ owner 点 → 服务以 7 退出 → `stable_copy.py run` 换版本（`git checkout`）、在空闲端口试起一次、失败就退回 → 再起服务。结果写 `.stable-outcome.json`，每换一次记一行 `.stable-history.jsonl`。这几个文件都不进仓库。
- 孩子用出来的数据住在体验版里：`lessons/<课>/explain_cache.json` 里点词补查和展开查到的、`lessons/<课>/tts/` 下现读的。换版本时留下（SPEC-008 R7）。学习记录在浏览器里，按 `localhost:8765` 存。
- 密钥：体验版里的 `api-keys.txt` 是换版本时从开发版拷的（只比字节）。发音词典 `WordsAudio/` 两份共用（和两个目录并排）。

## 外部服务

| 服务 | 谁调 | 什么时候 | 要不要翻墙 | 密钥 |
|---|---|---|---|---|
| 百炼 录音文件识别 `qwen-audio-3.0-asr-flash-filetrans` + 临时存储 | `asr_probe.py` | 备课第 2 步 | 不要 | 百炼 |
| 百炼 `qwen3-asr-flash`（机器耳朵） | `ear.py`（`ear_bounds.py`、`tests/test_audio.py`、`tts.py check` 用） | 备课第 5 步、验声音 | 不要 | 百炼 |
| 百炼 `cosyvoice-v3-flash`，声音 `loongemily_v3` | `tts.py`（经 `explain.py` 的现读） | 孩子点「听朗读」、词组或词典里没有的词 | 不要 | 百炼 |
| DeepSeek `deepseek-flash`（不开思考模式） | `llm.py`（`teach.py`、`explain.py` 用） | 备课第 6 步；孩子点「展开」、备课漏了的词 | 不要 | DeepSeek |
| 百炼兼容接口的 qwen 文字模型 | `llm.py`（只有 `compare_models.py` 用） | 比较模型时 | 不要 | 百炼 |
| 谷歌翻译的朗读 `translate.google.com/translate_tts` | `tts.py library` | 只在建发音词典时，一台电脑一次 | **要** | 不要（非正式接口，只在家里和熟人之间用） |

孩子和家长那一端（浏览器）不直接连任何外部服务，只连本机的本地服务（SPEC-000 R1）。

## 密钥

- `api-keys.txt`（仓库根目录，`.gitignore` 第一行）里分段写，`#qwen` 一段是百炼的、`#deepseek` 一段是 DeepSeek 的；只有 `pipeline/keys.py` 读它。
- 用到密钥的只有备课程序和本地服务；网页里没有。任何时候不打印、不进日志和报错、不放命令行参数（CLAUDE.md 红线）。
- 以后接服务器：本地服务的三个接口挪到服务器上，做一个网关，密钥统一放服务器（owner 2026-09-22）。

## 运行环境

工具清单、版本、端口、换电脑怎么搭在 `docs/environment.md`，这里只写和架构有关的。

- Python：conda 环境 pywork（路径在 CLAUDE.md「环境与命令」），用到的库：dashscope（百炼）、openai（调 DeepSeek 和百炼兼容接口）、pypdf（读讲稿）、numpy（算音量）、wordfreq（发音词典的词表）、imageio-ffmpeg、playwright。
- 浏览器：播放器自动检查用 Playwright 自带的 chromium；验声音用真的 Chrome（和 owner 一样）。
- 机器：Windows 11；不用显卡（识别和模型都在云上）。

## 以后会怎么变

- 家长上传材料、一条命令备课（SPEC-002 R1）：备课六步串起来，结构不变。
- 网页加本机小服务，还是客户端：待 owner 定（决策 D20）。
- 上服务器：本地服务的接口搬过去、加网关；播放器照旧只读课程文件、只连一个服务。
