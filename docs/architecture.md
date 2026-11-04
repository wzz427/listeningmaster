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
  web/ 播放器（浏览器里，五个文件，没有构建步骤）
        学习记录存在浏览器本地，能导出；
        对外模式下另有资料库侧边栏（web/library.js）
```

模块之间只通过文件交接：备课写文件，播放器读文件；播放器唯一连出去的是本地服务。

## 目录

| 位置 | 干什么 | 规格 |
|---|---|---|
| `demand.md` | owner 的需求原话、优先级、不做什么、约束 | — |
| `AGENTS.md` | ZCode 自动读到的入口：指针、开机三步、红线摘录；第一读物仍是 `CLAUDE.md`（决策 D36） | — |
| `idea.txt` | owner 起步时写的最初想法，只作历史 | — |
| `specs/` | 规格：`SPEC-000-overview.md` 是总需求和模块表，其余一块一份；`SPEC-template.md` 是空模板 | — |
| `docs/` | 本文、`workflow.md`（开发流程和验证）、`copies-and-release.md`（三版管理与发版的操作手册：改→测→交→验→上）、`environment.md`（开发环境和工具）、`deploy-listen-app.md`（对外版上线到阿里云的操作手册和日常运维）、`how-to-report.md`（发给 owner 的汇报怎么编排和自检，D59）、`decisions.md`、`lessons.md`、`debts.md`、`handoff.md`、`listening-led-course.md`（课程方案：理念、一集六步、单元阶段）；`research/` 放调研产出——`2026-09-12-products-teaching-tech-survey.md` 是三轮调研摘要（产品、教学研究、技术），报告一篇一文件、文件名带日期前缀（D46）；`refs/qwen-asr-api.md` 是百炼识别的官方文档存档；`history/` 放整批搬走的旧交接记录 | — |
| `materials/<课>/` | 原始素材：音频、讲稿、练习 | SPEC-002 |
| `lessons/<课>/` | 备好的一集，见下面「每一集的文件」 | SPEC-002 |
| `pipeline/slicing/` | 语义切割引擎（owner 2026-11-03 拍板收进一个包，算法一行没动）：六道工序＋一条命令＋版本＋金样考卷；怎么切准的细则住 SPEC-003、SPEC-004，怎么包住 SPEC-012 | SPEC-012 |
| `pipeline/slicing/audio.py` | 转音频：16k 单声道 wav（识别、量音量用）、m4a（播放器用）；用 imageio-ffmpeg 自带的 ffmpeg | SPEC-002 |
| `pipeline/slicing/asr_probe.py` | 上传临时存储、调百炼录音文件识别，存 `asr_raw.json` | SPEC-003 |
| `pipeline/slicing/transcript.py` | 从 BBC 讲稿 PDF／TXT 读出「谁说了什么」 | SPEC-003 |
| `pipeline/slicing/align.py` | 识别结果对齐讲稿、说话人、片头片尾、切句，写 `timeline.json`、`align_report.md`（有讲稿走这条） | SPEC-003 |
| `pipeline/slicing/no_transcript.py` | 无讲稿路的对齐（SPEC-013）：拼词、巨词大模型加空格＋词频兜底、标点并半句、编号归并起名，同样写 `timeline.json`、`align_report.md`；大模型回答缓存 `llm_cache.json` | SPEC-013 |
| `pipeline/slicing/refine_bounds.py` | 按音量精修句子起止，写 `bounds_report.md` | SPEC-004 |
| `pipeline/slicing/ear.py` | 机器耳朵：一段声音交给百炼 `qwen3-asr-flash` 听出是哪些词，带限流重试 | SPEC-004 |
| `pipeline/slicing/ear_bounds.py` | 机器耳朵查每句开头结尾、往外挪，最后照 `bounds_manual.json`、`speaker_manual.json` 改，写 `ear_report.md`；真听过的片段记进 `ear_cache.json` | SPEC-004 |
| `pipeline/slicing/run.py` | 引擎一条命令：串六步（识别已有就跳过）、按材料夹里有没有讲稿挑 align／no_transcript、写 `quality_report.md`（无讲稿课不出对上率）；退出码 10 音频／20 识别／30 其他，serve.py 按码报人话 | SPEC-012、SPEC-013 |
| `pipeline/slicing/version.py` | 引擎版本唯一出处，`timeline.json` 的 engine 字段从这读 | SPEC-012 |
| `pipeline/slicing/__init__.py` | 包标记＋导览注释 | SPEC-012 |
| `pipeline/measure_bounds.py` | 只看音量量句子边界干不干净，比较改边界前后 | SPEC-004 |
| `pipeline/teach.py` | 备课最后一步：每句中文、挑生词、调 `explain.prepare` 写那一行、分段、调 `tts.build` 拷朗读，写 `lesson.json`、`teach_raw.json` | SPEC-005 |
| `pipeline/explain.py` | 单词卡的内容：备课时整句写那一行；点词时补查、展开、词组现读；缓存 | SPEC-006 |
| `pipeline/tts.py` | 发音词典（建、查、拷进课程文件夹）、百炼 Emily 合成、抽听页 | SPEC-007 |
| `pipeline/tts_check.html` | `tts.py check` 用的抽听页模板 | SPEC-007 |
| `pipeline/llm.py` | 调大模型的统一口：deepseek 开头走 DeepSeek，qwen 开头走百炼兼容接口；关掉 deepseek 的思考模式 | SPEC-000 R5 |
| `pipeline/keys.py` | 从 `api-keys.txt` 读密钥，只读进内存 | SPEC-000 R2 |
| `pipeline/serve.py` | 本地服务，见下面「本地服务」；`--hosted` 起对外模式（SPEC-009 v7，线上、体验版、开发版看网站都是它）：**访客免登录直接听公共课库**（线上 `server-data/shared/lessons/`，本机两份就是仓库里的 `lessons/`，R14）、点词现查开放；注册/登录/登出、上传/资料库/删材料、讲稿补传（TXT/PDF/MD 文件，`/api/material/script`）、备课任务（串行队列：切割引擎一条命令＋`teach.py`，SPEC-012；或配置 `prep_command` 换假命令测试）仍要登录会话 | SPEC-001 R12、SPEC-009 |
| `pipeline/speak_lab.py` | 口语实验页的服务端（决策 D52，实验件、不进播放器和对外版）：8770 出页面和陪练提示词（拿 `lesson.json` 的标题、分段、生词、几句原话拼，教学规矩也在提示词里）；8771 当 WebSocket 桥，网页 ⇄ 百炼 Realtime 原样转发，密钥只在这一个进程；`mock` 假模型不花钱走整条事件链；`--selftest omni38\|audio31` 连真模型放一段课程音频验证 | —（实验，正式规格等 A/B 结论） |
| `pipeline/accounts.py` | 邮箱账号（对外版地基）：注册要邀请码、登录发会话、连错锁、密码只存 PBKDF2 哈希；数据住 `server-data/`（不进 git），布局 `server-data/<账号id>/{materials/<材料id>/{audio.*, script.txt, meta.json}, lessons/<课>/}`——材料 meta.json 的 state 就是 SPEC-009 的状态机（new/prepping/done/failed） | SPEC-009 |
| `pipeline/stable_copy.py` | 体验版和开发版：建体验版（自带网站配置和数据目录）、钉版本（要两份测试全过）、换版本（失败退回、留下用出来的数据）、退回上一版、双击后起网站的循环；见下面「三个住处、一套代码」 | SPEC-008 |
| `pipeline/compare_models.py` | 一次性：比较两个模型写的中文和生词判断，出 `model_compare.md` | SPEC-005 |
| `pipeline/ablation_no_transcript.py` | 一次性（2026-11-03）：无讲稿消融——识别原样（`asr_raw.json`）对金样 `timeline.json` 逐词逐句比对，说话人／巨词／预告漏进／碎句四个指标；离线不花钱，细账出 `ablation/`（不进仓库） | —（实验，结论住 `docs/research/2026-11-03-no-transcript-ablation.md`） |
| `web/index.html`、`web/style.css`、`web/app.js` | 播放器，见下面「播放器」 | SPEC-001 |
| `web/login.html` | 登录页（对外模式专用）：注册（要邀请码）／登录（只要邮箱密码，记住了邮箱第二次只输密码），注册成功即登录；底部「先直接体验」直达 /web/（v7：访客默认不经过这页）；自包含样式，不依赖 style.css | SPEC-009 |
| `web/library.js` | 资料库侧边栏、上传面板（拖放区主角＋讲稿文件）、空库的播放器（不挡路，卡片里一句邀请）（对外模式专用）：app.js 只在服务报 `copy=hosted` 时进来（hostedStart/hostedLessonMissing 两个入口）；两区四状态、备课轮询、材料变课的高亮和通知、进度点（读 app.js 的学习记录键）、「＋讲稿」补传、登出。v7 匿名态（`/api/library` 的 `user` 为 null）：只见课区（标题「听力材料」＝公共库）、没有上传和材料区、底部小「登录」。本地模式一个字节都不执行 | SPEC-009 R8 |
| `web/speak-lab.html` | 口语实验页（决策 D52，自包含单文件）：两个实时语音模型 A/B 一键切换、孩子/大人两种口吻、麦克风收发（AudioWorklet，上行 16k 下行 24k）、实时转写、每轮「接话」延迟、10 分钟封顶、聊完存转写（文本和 JSON）、「事件」面板看原始事件（协议排错用）。只连本地 8771 的桥，不直接连百炼 | —（实验，同 `pipeline/speak_lab.py`） |
| `web/fonts/` | 放在本地的字体：Literata（英文正文）、DM Mono（数字）、Noto Serif 裁出来的音标字体，各带许可证 | SPEC-001 R22、SPEC-006 R8 |
| `web/art/` | 环节进入页（节目卡）的两张固定配图：`warmup.jpg`（开场：调频）、`listen.jpg`（正片：夜听），百炼 qwen-image 生成后转 jpg；换图＝换这两个文件 | SPEC-011 R1 |
| `tests/test_player.py` | 播放器的自动检查（Playwright），编号对应各规格的 A 编号 | `docs/workflow.md` |
| `tests/test_audio.py` | 验声音：录下真的 Chrome 放出来的声音，对时间、机器耳朵听、出试听页 | SPEC-004 R7 |
| `tests/test_slicing.py` | 切割引擎的金样考卷：四课离线重放，timeline 逐句对标准答案，另带咬人自检；无讲稿路同四课对 `tests/fixtures/free/` 的 free 金样（识别＋大模型缓存都在那，不联网）；改 `pipeline/slicing/` 必过 | SPEC-012、SPEC-013 |
| `tests/make_free_fixtures.py` | 造无讲稿考卷的考题和答案（调一次大模型、几分钱）：识别考题＋`llm_cache`＋free 金样写进 `tests/fixtures/free/`；改了无讲稿的提示词或规则后重跑 | SPEC-013 |
| `tests/test_docs.py` | 文档和代码对不对得上 | `docs/workflow.md` |
| `tests/test_accounts.py` | 账号模块的单元检查（注册、登录、会话、连错锁、密码不落盘），临时目录里跑 | SPEC-009 |
| `tests/test_hosted_server.py` | 对外模式的自动检查：真起服务真发请求——访客免登录（公共课、点词）、上传等账号接口挡 401、注册登录登出、noindex、限流、无「更新」接口 | SPEC-009 |
| `tests/test_hosted_upload.py` | 上传、资料库、删材料的自动检查：真上传假音频字节——类型和大小闸、标题讲稿落盘、两账号隔离、课路径按账号指路 | SPEC-009 |
| `tests/test_hosted_prep.py` | 备课任务的自动检查：假备课命令跑通状态机（排队、备课中挡重复点、成功变课、失败人话原因、重试） | SPEC-009 |
| `tests/test_hosted_frontend.py` | 资料库前端整条用户路的自动检查（Playwright 开真页面）：匿名直接进站听公共课 → 登录注册进站空库待机 → 上传（选错文件的人话）→ 备课轮询到变课高亮 → 点课切换 → 进度点 → 失败重试 → 删除 → 登出 → 体验版网站的「更新」灰/亮、线上没有。全过时把代码指纹记在 `.site-tests-passed.json`（钉版本要它，SPEC-008 R4） | SPEC-009 R8、SPEC-008 R12 |
| `tests/test_stable_copy.py` | 换版本的自动检查：临时目录里造真的仓库和体验版，真的切版本、真的起网站、真的走一遍「点更新 → 停 → 换 → 起回来」 | SPEC-008 |
| `start-trial.bat` | 双击：旁边有体验版就转去体验版，然后调 `pipeline/stable_copy.py run` 起体验版的网站（8790）并打开浏览器；服务已开着就只开一页浏览器。只放英文字符 | SPEC-008 R2 |
| `start-speak-lab.bat` | 双击：起口语实验页（`pipeline/speak_lab.py`）并打开浏览器，关窗口就停。实验件，只放英文字符 | —（D52 实验） |
| `requirements.txt` | 服务器上要装的 Python 包（版本是开发机验证过的一组；wordfreq 只有重建发音词典才要，没列） | SPEC-009 R10 |
| `deploy/Dockerfile`、`deploy/docker-compose.yml`、`deploy/server-config.example.json`、`deploy/caddy-listen-app.conf`、`.dockerignore` | 发布物料（182.92.206.53 容器形态，SPEC-009 v8）：应用镜像（serve.py 对外模式＋备课六步都在容器里）、compose（容器名 listeningapp，密钥/配置/账号数据/备课台/共享发音词库全是挂载卷；`name: listening` 防止和别的 compose 撞项目名）、配置模板（复制成仓库根的 server-config.json，不进 git）、网关站点块、镜像构建排除清单 | SPEC-009 R10、R11 |
| `.zcode/commands/wrap.md` | 收尾命令 `/wrap`：压缩上下文之前把只活在对话里的东西写到盘上、扫文档、提交 | — |
| `api-keys.txt` | 密钥，不进仓库（`.gitignore` 第一行） | SPEC-000 R2 |

## 每一集的文件（`lessons/<课>/`）

| 文件 | 谁写 | 谁读 | 进仓库 |
|---|---|---|---|
| `audio_16k.wav` | `slicing/asr_probe.py`（没有时 `slicing/refine_bounds.py` 补） | 精修、机器耳朵 | 不进，随时能重转 |
| `audio.m4a` | `slicing/audio.py` | 播放器 | 进 |
| `asr_raw.json` | `slicing/asr_probe.py` | `slicing/align.py` | 进（识别要花钱，留着原样） |
| `timeline.json` | `slicing/align.py`，`slicing/refine_bounds.py`、`slicing/ear_bounds.py` 原地改起止、最后盖 engine 版本 | `teach.py`；`tests/test_slicing.py` 拿它当标准答案 | 进 |
| `ear_cache.json` | `slicing/ear_bounds.py`（真听时记：这一段听成了什么） | `slicing/ear_bounds.py`（重放）、`tests/test_slicing.py` | 进（机器耳朵花过钱换来的，考卷离线重放的前提） |
| `align_report.md`、`bounds_report.md`、`ear_report.md`、`quality_report.md` | 第 3、4、5 步、`slicing/run.py` | 人 | 进 |
| `bounds_manual.json` | 人（owner 听过定的） | `slicing/ear_bounds.py` | 进 |
| `speaker_manual.json` | 人（说话人手定层；250123 结尾预告 2026-11-03 从 timeline 搬进文件） | `slicing/ear_bounds.py` | 进 |
| `lesson.json` | `teach.py` | 播放器、`explain.py`、`tts.py check` | 进 |
| `teach_raw.json` | `teach.py` | 人 | 进 |
| `explain_cache.json` | 本地服务（点词补查、展开） | 本地服务 | 不进，运行时按处累积（线上在挂载卷、本机在本地）；重查一遍只花几分钱，换来的是仓库不动账（2026-11-03 改：原来写着进，实际早就各存各的，还把 `260821` 一份裹进了仓库六周没人发现——`tests/test_docs.py` D6 拿这张表双向对账） |
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
| `warmup.words[].term`、`warmup.words[].ipa`、`warmup.words[].zh`、`warmup.words[].sentence`、`warmup.words[].sentenceZh`、`warmup.words[].termAudio`、`warmup.words[].sentenceAudio` | 预热关键词（SPEC-010）：词或词组、音标（词组可空）、中文、配的简单句、句子的中文、两条读音文件的路径 |
| `tts.voice`、`tts.files` | 朗读用的是谁的声音；词 → 朗读文件（相对课程文件夹） |

## 本地服务（`pipeline/serve.py`）

- 只听本机 127.0.0.1，默认端口 8766（claude 自己看播放器、`tests/test_player.py` 的服务都是这个模式）；网页地址 http://localhost:8766/web/ ，`?lesson=<课>` 选哪一集（默认 260821）。
- 静态文件：支持 Range（从文件中间取一段），不然音频跳不到指定的秒数；一律不缓存，改了代码刷新就生效。`python -m http.server` 不支持 Range，不能用（`docs/lessons.md` 2026-09-12）。
- 接口，请求都是 JSON，都带 `lesson`；课名只许字母数字、下划线、连字符，防止借路径读别的文件：
  - `POST /api/explain` `{sentence, word}` → 那一行：先查缓存，再查 `lesson.json` 里备课写好的，都没有才问模型。`sentence` 是 `w<数字>` 时是预热配句（第几个关键词），走 `explain.warm_explain`，缓存键同样带 `w` 前缀，不碰正文的句号（SPEC-010 R5）。
  - `POST /api/more` `{sentence, word}` → 展开的内容，查过的存进缓存；`w<数字>` 同上走 `explain.warm_more`。
  - `POST /api/speak` `{key, text}` → `{file}`：词组或词典里没有的词的朗读文件，没有就让 Emily 现读、存下来。
  - 出错只回 `{"error": 错误的种类}`，不回详情：详情里可能带着请求头（SPEC-000 R2）。
- 换版本的两个接口（SPEC-008），不带 `lesson`：
  - `GET /api/version` → `{version, copy, hosted, update: {waiting, what}, failed}`：服务起来时是哪个提交（页面拿它判断自己旧没旧，不显示）、是体验版还是开发版还是线上、是不是网站（页面拿它决定要不要叫资料库侧边栏）、有没有一版等 owner 点「更新」和那一版多了什么、上一次没换成的那句话。钉住的是哪个提交不给。
  - `POST /api/update` → 202 后服务以退出码 7 停下；没有要换的、或者服务不是 `--managed` 起的，回 409。体验版的网站有它；线上 404。
- 命令行：`serve.py [端口] [--open] [--managed]`（本地模式）、`serve.py --hosted [--port N] ...`（对外模式）。`--open` 起来后打开浏览器；`--managed` 表示有 `stable_copy.py run` 负责换完版本把它拉起来。开发版旁边有体验版时，开发版拿 8790 当场拒绝（看网站用 8791、播放器用 8766）。
- 独占端口：Python 自带的 HTTPServer 在 Windows 上允许两个服务同时占一个端口，这里关掉了（`docs/lessons.md` 2026-09-24）。
- **对外模式**（`serve.py --hosted`，读仓库根 `server-config.json`（不进 git）：invite、port（默认 8790）、bind、data_dir、shared_root、secure_cookie。三个住处都用它：线上、owner 本机的体验版（双击 `start-trial.bat`）、claude 自己看网站（8791）；SPEC-009 v7）：
  - **访客免登录**：`/web/` 页面、`/lessons/` 音频、`GET /api/library`、点词三个接口（explain/more/speak）匿名放行——课指到公共库 `server-data/shared/lessons/`（R14，只放 owner 拍板可公开的课）。
  - 按身份指路：已登录 `/lessons/` 先指自己账号目录（`server-data/<账号id>/lessons/`，互不可见）、没有的课落公共库；匿名只有公共库；点词接口的课目录同一套逻辑。
  - `/api/library` 返回 `{user（null＝匿名）, materials（匿名恒空）, lessons（已登录＝自己的＋公共库，重名自己优先）}`。
  - 要会话的（匿名 401）：注册/登录/登出（`pipeline/accounts.py`）、上传、备课、删材料、补讲稿。
  - 所有响应带 `X-Robots-Tag: noindex`；POST 每 IP 每分钟 30 次（反代下取 X-Forwarded-For 第一段）；线上 `/api/version` 报 hosted、`/api/update` 404——体验版除外（报 stable、有「更新」，SPEC-008 R12）。
  - 完整需求在 `specs/SPEC-009-hosted-trial.md`；上线手册 `docs/deploy-listen-app.md`（域名 `listening.app.bayescode.com`）。

## 播放器（`web/`）

- 三个文件，纯 HTML + JavaScript + CSS，不用框架、没有构建步骤（决策 D14）。
- `app.js` 按功能分块，块头有注释：启动、分段、声音（渐强渐弱、准点停）、跳句（两种播法）、画面、进度条、单词、全文、按钮和键盘。开头写着几条要记住的理由。
- 声音走 Web Audio 的音量节点，停之前在上面做渐弱（SPEC-001 R16）；验声音时在同一个节点后面接录音（`tests/test_audio.py`）。
- 学习记录和设置存在浏览器本地（`localStorage`，按课名分开），「导出」存成文件（决策 D9）。另有按课记的一次性开关：`warmup-done`（这课预热过没有，SPEC-010）、`listen-intro-done`（这课过没过「精听」节目卡，SPEC-011）。
- 字体全在 `web/fonts/`，中文用系统字体（决策 D19）。
- 换版本（SPEC-008）：每分钟、切回页签时问一次 `/api/version`；服务换了版本挂「这一页旧了」；「更新」只在体验版里有——平时灰着、钉了新版本亮起来（D55）。刷新前把当前句子记在 `sessionStorage`，刷新后回到这一句。

## 三个住处、一套代码（SPEC-008 v2，D55）

- 开发版：这个仓库目录，claude 改（随时可能改到一半）。体验版：旁边的 `ListeningMaster-stable`（两份同在 `BayesAPP/` 下，2026-10-25 搬家），这个仓库的第二个工作目录（`git worktree`，不挂分支），owner 测新版本用的，一个字不手改。正式版：线上网站（`listening.app.bayescode.com`），孩子和各家用，只发体验版验过的那一版。三份共用一个 git 仓库，体验版能切到开发版里的任何提交。
- 双击任何一份里的 `start-trial.bat`，起的都是体验版的网站，地址 http://localhost:8790/ ：访客直接听、能登录能上传，配置（`server-config.json`）和账号数据（`server-data/`）是体验版自己的一份（不进仓库，`stable_copy.py` 补齐），公共课就是这一版仓库里的 `lessons/`。
- 新版本怎么过去：claude `stable_copy.py invite` 钉一版（要求 `tests/test_player.py` 和 `tests/test_hosted_frontend.py` 都对这份代码全过，全过时把代码指纹记在开发版根上的 `.player-tests-passed.json`、`.site-tests-passed.json`）→ 钉的记录写在体验版根上的 `.stable-invite.json` → 页面右上角的「更新」亮起来 → owner 点 → 服务以 7 退出 → `stable_copy.py run` 换版本（`git checkout`）、在空闲端口试起一次、失败就退回 → 再起服务。结果写 `.stable-outcome.json`，每换一次记一行 `.stable-history.jsonl`。这几个文件都不进仓库。
- owner 用出来的数据住在体验版里：`lessons/<课>/explain_cache.json` 里点词补查和展开查到的、`lessons/<课>/tts/` 下现读的、上传材料点备课时留下的备课台（`materials/<材料号>/` 等）。换版本时留下（SPEC-008 R7）；账号和上传的材料在体验版自己的 `server-data/` 里，换版本碰不到。登录和学习记录在浏览器里，按 `localhost:8790` 存。
- 密钥：体验版里的 `api-keys.txt` 是起服务和换版本时从开发版拷的（只比字节）。发音词典 `WordsAudio/` 两份共用（和两个目录并排）。
- 日常操作（交版、点「更新」、退回、上线发哪一版）：手册在 `docs/copies-and-release.md`。

## 外部服务

| 服务 | 谁调 | 什么时候 | 要不要翻墙 | 密钥 |
|---|---|---|---|---|
| 百炼 录音文件识别 `qwen-audio-3.0-asr-flash-filetrans` + 临时存储 | `pipeline/slicing/asr_probe.py` | 备课第 2 步 | 不要 | 百炼 |
| 百炼 `qwen3-asr-flash`（机器耳朵） | `pipeline/slicing/ear.py`（`slicing/ear_bounds.py`、`tests/test_audio.py`、`tts.py check` 用） | 备课第 5 步、验声音 | 不要 | 百炼 |
| 百炼 `cosyvoice-v3-flash`，声音 `loongemily_v3` | `tts.py`（经 `explain.py` 的现读） | 孩子点「听朗读」、词组或词典里没有的词 | 不要 | 百炼 |
| DeepSeek `deepseek-flash`（不开思考模式） | `llm.py`（`teach.py`、`explain.py` 用） | 备课第 6 步；孩子点「展开」、备课漏了的词 | 不要 | DeepSeek |
| 百炼兼容接口的 qwen 文字模型 | `llm.py`（只有 `compare_models.py` 用） | 比较模型时 | 不要 | 百炼 |
| 百炼 Realtime `qwen3.8-omni-flash-realtime`（口语实验模型 A） | `speak_lab.py` 的桥 | 口语实验页开聊（D52，实验） | 不要 | 百炼 |
| 百炼 Realtime `qwen-audio-3.1-realtime-plus`（口语实验模型 B） | `speak_lab.py` 的桥 | 同上 | 不要 | 百炼 |
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
