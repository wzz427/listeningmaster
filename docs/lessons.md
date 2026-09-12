# 教训 —— 哪些路别再走

> 答什么：真踩过的坑。撞到报错时搜报错字眼；开机扫最上面几条。
> 不归档、不拆分：教训没有生命周期，用法是搜。每条：症状（贴真实报错字眼）/ 根因 / 修法 / 怎么确认修好了。

## 最容易撞的

| 症状 | 一句话因 | 修法 |
|---|---|---|
| 密钥出现在对话里 | 想「遮蔽后再打印」，遮蔽规则没覆盖新格式 | 任何情况下都不打印密钥文件，读取只走 `pipeline/keys.py` |
| `conda install ffmpeg` 报 `UnicodeDecodeError('gbk'...)` 后整体回滚 | 它顺带装的图形库在中文 Windows 上跑不完安装脚本 | 改用 `pip install imageio-ffmpeg`，它自带一个独立的 ffmpeg |
| 终端里中文变成乱码 | Windows 控制台默认不是 UTF-8 | 程序入口加 `sys.stdout.reconfigure(encoding="utf-8")` |
| 百炼报找不到文件或地址无效 | 录音文件转写模型只收公网地址，不收本地路径 | 用 `dashscope.utils.oss_utils.upload_file` 传到临时存储，并加请求头 `X-DashScope-OssResourceResolve: enable` |

## 全部（新的在上）

### 2026-09-12 · 密钥被打印进了对话

- 症状：为了看密钥文件的结构，用正则把密钥替换成星号后打印，结果 `sk-ws-` 开头的那把没被遮住，原文进了会话记录。
- 根因：遮蔽规则假设密钥是 `sk-` 加字母数字，新格式中间带了连字符。靠「遮蔽后打印」本身就是错的做法，遮蔽规则永远追不上新格式。
- 修法：密钥文件一律不打印、不 cat、不 grep。要用就在程序里读（`pipeline/keys.py`），要确认格式就只判断读没读到，不输出内容。
- 怎么确认修好了：`pipeline/asr_probe.py` 全程没有任何一行输出包含密钥，上传得到的地址也只打印前缀。

### 2026-09-12 · conda 装 ffmpeg 失败并回滚

- 症状：`conda install -n pywork -c conda-forge ffmpeg` 跑到最后报 `An error occurred while installing package 'conda-forge::gdk-pixbuf'`，接着 `UnicodeDecodeError('gbk', ... 'illegal multibyte sequence')`，整个事务回滚，ffmpeg 没装上。
- 根因：conda-forge 的 ffmpeg 会连带装 gdk-pixbuf，它的安装后脚本输出中文报错，conda 用 GBK 解码失败。
- 修法：`pip install imageio-ffmpeg`，用 `imageio_ffmpeg.get_ffmpeg_exe()` 拿到独立的 ffmpeg 可执行文件（见 `pipeline/audio.py`）。代价是没有 ffprobe，用 `ffmpeg -i` 读信息代替。
- 怎么确认修好了：`pipeline/audio.py` 能把 mp3 转成 16kHz 单声道 wav，`probe()` 能读出时长和声道数。
