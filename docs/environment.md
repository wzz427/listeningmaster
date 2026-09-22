# 开发环境

> 答什么：在这台电脑上开发要用到哪些环境和工具、各管什么、装在哪；换一台电脑从零搭起来按什么顺序；这台 Windows 上的命令行有哪些坑。
> 谁何时读：第一次在这个仓库干活；换电脑；装包、升级包之前；命令行出了怪事（乱码、反斜杠丢了、包冲突）时。
> 怎么变短：只写现在装着、用着的；换掉的工具写一句进 `docs/decisions.md`，这里删掉。踩坑的完整经过住 `docs/lessons.md`，这里只留一句和修法。

## 一张表看全

| 东西 | 在哪 · 什么版本 | 管什么 |
|---|---|---|
| 电脑 | Windows 11 家庭中文版；显卡 RTX 500 Ada（4GB 显存，本项目用不上：识别和模型都在云上） | — |
| Python | conda 环境 pywork：`C:\Users\wzzpk\.conda\envs\pywork\python.exe`，Python 3.12。**不在 PATH 上**，一律用绝对路径调；不用系统 Python，不另建环境 | 备课程序、本地服务、全部测试 |
| dashscope 1.25 | pywork 里 | 百炼：录音文件识别、临时存储、机器耳朵、Emily 朗读 |
| openai 3.3 | pywork 里 | 按 OpenAI 兼容接口调 DeepSeek 和百炼的文字模型（`pipeline/llm.py`） |
| pypdf 6.18 | pywork 里 | 读 BBC 讲稿 PDF |
| numpy 2.4 | pywork 里 | 算音量（句子边界、验声音） |
| wordfreq 3.1 | pywork 里 | 发音词典的常用词排名 |
| imageio-ffmpeg 0.6 | pywork 里，自带一个独立的 ffmpeg | 转音频、切片段。**不要** `conda install ffmpeg`（见「坑」） |
| playwright 1.59 + chromium | pywork 里，chromium 已下载 | 播放器自动检查 `tests/test_player.py` |
| Google Chrome | `C:\Program Files\Google\Chrome\Application\chrome.exe` | 验声音 `tests/test_audio.py` 用真的 Chrome（和 owner 一样） |
| fonttools 4.62 + brotli 1.2 | pywork 里 | 查字体里有没有某个字符、裁字体（做音标字体用的，见下） |
| git 2.52 | Git for Windows | 版本管理。本地分支 master |
| 发音词典 | 仓库外并排的 `WordsAudio/`（和 `ListeningMaster/` 同在 `WorkSpace/` 下） | 5 万词的谷歌英音，备课时拷用（SPEC-007 R5） |
| 密钥文件 | 仓库根目录 `api-keys.txt`，不进仓库 | 百炼、DeepSeek 的密钥（`docs/architecture.md`「密钥」） |
| 翻墙工具 | 这台电脑上有 | **只**在建发音词典时要用；别的一律不许依赖（SPEC-000 R1） |
| Claude Code | owner 用它和 claude 一起开发 | 仓库里的 `/warp` 命令在 `.claude/commands/warp.md`；改界面前加载 frontend-design 技能（CLAUDE.md） |

## 端口

| 端口 | 谁用 |
|---|---|
| 8765 | 平时的本地服务：`start-player.bat` 或 `pipeline/serve.py 8765`，owner 就用这个 |
| 8799 | `tests/test_player.py` 自己起的服务 |
| 8798 | `tests/test_audio.py` 自己起的服务 |

测试各用各的端口，owner 开着播放器时也能跑测试。本地服务改了代码（尤其是接口）要关掉那个黑窗口重开，网页刷新不会让服务换新代码。

## 换一台电脑从零搭

1. 装 Miniconda（或 Anaconda），建环境：`conda create -n pywork python=3.12`。
2. 装包：`<pywork python> -m pip install dashscope openai pypdf numpy wordfreq imageio-ffmpeg playwright fonttools brotli`，再 `<pywork python> -m playwright install chromium`。装完 `<pywork python> -m pip check`，要显示没有冲突。
3. 装 Google Chrome（验声音要用）。
4. 拷仓库；在根目录放 `api-keys.txt`，里面 `#qwen` 下一行是百炼的密钥、`#deepseek` 下一行是 DeepSeek 的。只在程序里读，不许打印、不许 cat（CLAUDE.md 红线）。
5. 发音词典：直接把旧电脑的 `WordsAudio/` 整个拷过来最省事；没有就开翻墙跑 `<pywork python> pipeline/tts.py library --top 50000`（约 2.5 小时、约 575MB，断了重跑接着取）。
6. 自检：`tests/test_docs.py`（不到 1 秒）→ `tests/test_player.py`（不到 1 分钟，64 项全过）→ 双击 `start-player.bat` 能听。要验声音再跑 `tests/test_audio.py`。

孩子和家长那边的电脑只需要浏览器和一个起本地服务的办法（现在是 `start-player.bat`），不需要翻墙、不需要密钥以外的任何东西；以后上服务器，连密钥都不用放他们那边（SPEC-000「以后」）。

## 装包、升级包之前

- 先 `<pywork python> -m pip install --dry-run <包>`，看它会不会顺手降级别的包；有降级就别装，换个办法。2026-09-22 装 gTTS 把 click 降到 8.1.8，和 typer 冲突（`docs/lessons.md`），已卸掉、click 装回 8.5.0。
- 装完跑 `pip check` 和 `tests/test_player.py`。
- 新装的包写进上面的表和「从零搭」第 2 步。

## 这台电脑上的坑（完整经过在 `docs/lessons.md`）

| 症状 | 修法 |
|---|---|
| 终端里中文变成乱码，或者 `UnicodeEncodeError: 'gbk' codec can't encode` | 程序入口加 `sys.stdout.reconfigure(encoding="utf-8")`（仓库里的程序都加了）；临时用 `python -c` 打印中文或音标时，前面加 `PYTHONIOENCODING=utf-8` |
| `conda install ffmpeg` 报 `UnicodeDecodeError('gbk'...)` 后整体回滚 | 用 imageio-ffmpeg 自带的 ffmpeg（`pipeline/audio.py`）；没有 ffprobe，用 `ffmpeg -i` 读信息 |
| 在 claude 的 Bash 里用 heredoc 写含反斜杠的 Python 脚本，`\\n` 变成了换行、替换位置差一个字符 | 这里的 Bash 会把 `\\` 吃成 `\`，加了引号的 heredoc 也一样；要写反斜杠一律用 Edit 工具逐处改 |
| 用 `python -m http.server` 起服务，点下一句只能听到第一句 | 它不支持从文件中间取一段；用 `pipeline/serve.py` |
| Bash 里没有 `bc` | 算时间用 Python |
| 编辑器（Pyright）报 `Cannot access attribute "reconfigure" for class "TextIO"`、`Import "tts" could not be resolved` | 误报：程序运行时把 `pipeline/` 加进了搜索路径，`sys.stdout` 运行时有这个方法；不用改 |
| 密钥差点进了对话 | 任何情况下都不打印、不 cat、不 grep 密钥文件，读取只走 `pipeline/keys.py` |

## 做过一次、以后可能再做的操作

- **裁音标字体**（2026-09-23，`web/fonts/noto-serif-ipa-400.woff2`）：从 notofonts 的 GitHub 取完整的 `NotoSerif-Regular.ttf`，用 fonttools 带的 pyftsubset 裁到只剩英文字母和音标符号：
  `pyftsubset NotoSerif-Regular.ttf --unicodes="U+0020-007E,U+00E6,U+00E7,U+00F0,U+014B,U+0250-02AF,U+02B0-02FF,U+0300-036F,U+03B8,U+1D4A,U+203F,U+2019" --flavor=woff2 --layout-features='kern,mark,mkmk,ccmp' --output-file=noto-serif-ipa-400.woff2`
  （pyftsubset 在 pywork 的 `Scripts` 目录里。）要显示别的特殊符号，先用 fonttools 查字体里有没有：`TTFont(文件).getBestCmap()` 里有那个字符的编号才算有。选 Noto Serif 是因为它没有保留字体名，裁过以后照样叫这个名字不违反许可；Charis SIL 有保留字体名，裁过就得改名。
- **比较两个模型写的内容**：`pipeline/compare_models.py`，结果写到 `lessons/<课>/model_compare.md`。
