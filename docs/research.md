# 调研摘要

> 整理时间：2026-09-12。来源是三轮网络调研：国内产品、海外产品与教学研究、技术方案。
> 小红书、Reddit 等社区内容大多抓取不到，所以用户评价偏少。标注"未核实"的内容，引用前请先查证。
> 本文是**摘要**；完整的调研报告一篇一份，住在 `docs/research/` 文件夹（第一篇：`docs/research/listening-led-course-design.md`，2026-09-26）。

---

## 一、国内同类产品

| 产品 | 句子级播放 | 可借鉴的点 | 槽点 |
|---|---|---|---|
| **每日英语听力**（欧路） | 点句播放；8 档变速；单句循环；单句听写或全文听写；语音高亮跟随 | "重点单词智能提示"可按初中、高中、**PET**、托福等分级，在生词旁标简释；AI 段落解析，可以追问 | 翻译要开 VIP；被评价"适合已清楚自己想听什么的人" |
| **可可英语** | 视频精听"4 步法"；单句循环；单句听写；逐词跟读打分 | 按 CEFR 定级推荐节目；九宫格听力游戏 | UI 繁琐；会员贵；自动续费被投诉 |
| **扇贝听力口语** | 盲听、选词填空、拼写三种模式 | **"智能填空"：系统挑重点词挖空，答不出给提示**；错题集；打卡提醒 | 有人认为孤立单句"无头无尾，作用很小"；跟读评分虚高 |
| **Aboboo**（PC） | 自动断句；三种复读模式：标记（逐句）、**一键（连续播放，随时退回）**、双键（AB 区间） | 复读次数可设；听写分抠词、句子、全文三级；跟读达到 60 分才进下一句 | 闪退；iOS 版 2021 年后停更 |
| **听点点**（2024） | 导入任意音视频，一键生成双语字幕；AB 循环；字幕隐藏 | 学习流程是"盲听 → 双语对照 → 影子跟读"；CEFR 难度分析；生词本会记录原句 | — |
| **少儿趣配音** | 先原速盲听，再用 0.5 倍速分解发音 | **AI 生成连读专项题**（这是它官网的自述） | — |

来源：[欧路](https://www.eudic.net/v4/en/app/ting)、[扇贝](https://sj.qq.com/appdetail/com.shanbay.listen)、[Aboboo 复读文档](https://www.aboboo.com/docs/ref/listen/overview.html)、[少数派·自动断句播放器](https://sspai.com/post/69869)、[听点点](https://apps.apple.com/cn/app/id6741526657)、[趣配音](https://www.qupeiyin.com/marticle/742)

## 二、海外同类产品

| 产品 | 要点 |
|---|---|
| **Language Reactor** | 看 Netflix/YouTube 时显示双语字幕；一键回到上一句；可以设置每句自动暂停。释义是机器翻译，理解不了语境 |
| **LingQ** | 边读边听，生词按"新词 / 学习中 / 已掌握"标色。**用户吐槽最多的是转写缺段、文本和声音不同步** |
| **Migaku** | 点一个词，就生成一张复习卡：单词、原句、原声片段、截图，进入间隔重复复习 |
| **Lingopie** | 单句循环、跟读。槽点是字幕不同步、AI 翻译太直译 |
| **LyricsTraining** | 歌词挖空，按比例分级（10% / 25% / 50% / 100%）；填不对视频就不往下放 |
| **Daily Dictation** | 免费，流程是"听 → 打字 → 核对 → 朗读" |
| **YouGlish** | 输入一个词，找出大量真人说这个词的视频片段，适合补充单词发音 |
| **BBC Learning English 官方 app** | **2023-12 已停运**，现在只剩网站和播客 |
| **Langua / Trancy**（AI 类） | AI 主要用来做语境释义、解释句子、自动出题。**还没有产品把 AI 用在诊断"为什么没听出来"上** |

来源：[Language Reactor 评测](https://languavibe.com/language-reactor-review/)、[LingQ 论坛·不同步](https://forum.lingq.com/t/whisper-audio-transcription-text-completely-out-of-sync-with-sound/2280901)、[Migaku](https://migaku.com/blog/language-fun/sentence-mining-guide-learn-vocabulary-faster)、[LyricsTraining](https://fltmag.com/lyricstraining/)、[Langua 评测](https://lingtuitive.com/blog/langua-ai-tutor-review)

## 三、二语听力研究：支撑设计的依据

1. **Field 的"诊断式教学"**：听力分两步，先把声音解码成词（decoding），再理解意思（meaning building）。他主张不要只核对答案，而要找出理解在哪一步断掉，再用短片段听写、音素辨别之类的小练习去补。见 Field, *Listening in the Language Classroom* (CUP 2008)；[Conti 对 Field 的整理](https://gianfrancoconti.com/2025/03/19/transforming-l2-listening-instruction-powerful-insights-from-prof-john-field-the-leading-expert-in-the-field/)。
2. **"认识的词听不出来"**：Goh (2000) 访谈了 40 名华语背景学习者，一半的问题出在感知层面，最典型的就是认识的词听不出来，水平越低越严重。[ERIC](https://eric.ed.gov/?id=EJ601557)
3. **连读、弱读是可以教的**：显式教学能提高听力理解，不过已有研究多是小样本。
4. **字幕**：
   - 看英文字幕视频，对理解和词汇都有明显帮助（Montero Perez 2013 元分析，理解 g=0.99）。[链接](https://www.sciencedirect.com/science/article/abs/pii/S0346251X13001012)
   - **只显示关键词的字幕，效果不比没有字幕好**，所以字幕要显示整句。[ReCALL 2014](https://www.cambridge.org/core/journals/recall/article/abs/is-less-more-effectiveness-and-perceived-usefulness-of-keyword-and-full-captioned-video-for-l2-listening-comprehension/9AD29F86C1752148FDBB500921922223)
   - 字幕帮的是"理解"，未必在训练耳朵。所以看完字幕后，应该再用原速听一遍。
5. **听前准备**：
   - **Chang & Read (2006)**：四种听前支持里，**预教词汇最没用**。提供话题背景最有效，其次是重复听。[ERIC](https://eric.ed.gov/?id=EJ753072)
   - Elkhafaifi (2005)：先看题比先学词效果好。
   - 充分理解大约需要认识 95% 的词（van Zeeland & Schmitt 2013）。
6. **听写**有效（Kiany & Shiramiry 2002）。**影子跟读**对低水平学习者的理解有帮助（Hamada 2016）。
7. **元认知循环**：听前预测 → 听 → 核对 → 再听 → 反思。听力弱的学习者从中获益更多（Vandergrift & Tafaghodtari 2010）。
8. **泛听**：低水平学习者需要大量能听懂的输入（Renandya & Farrell 2011）。

## 四、技术调研要点

- **ASR 与对齐**：
  - 本地方案：首选 WhisperX（faster-whisper 转写，再用 wav2vec2 做强制对齐），也可以用 Qwen3-ASR + Qwen3-ForcedAligner（开源，对齐精度更高，但要用 Linux/WSL）。
  - stable-ts 已于 2026-05 归档，aeneas 和 Gentle 已经过时，都不推荐。
- **讲稿不是逐字稿时怎么处理**：不要把整篇讲稿当提示词喂给识别模型，这样容易产生幻觉。做法是以 ASR 结果为准，和讲稿做词级序列对齐，再合并：拼写、说话人、分句参考讲稿，内容以录音为准。
- **说话人**：直接继承讲稿里的说话人标注就行，基本不需要说话人分离模型。
- **词表与词典**：
  - ECDICT：MIT 协议，有音标、中文释义、柯林斯星级、牛津 3000、考试标签，**但没有 CEFR 字段**。
  - 剑桥 B1 Preliminary 词表：官方 PDF 可以免费下载，但有版权，适合自用。
  - CEFR-J：注明来源即可商用。
  - SUBTLEX：词频表。
- **大模型**：国内可以直接调用 DeepSeek、通义千问、豆包等，一集的教学内容花不到 0.1 元。海外的 Claude、GPT、Gemini 在国内大陆官方不可用。
- **前端**：用 HTML5 audio 加时间戳 JSON 就能做。词高亮要用 `requestAnimationFrame` 轮询，因为 `timeupdate` 事件触发太稀。**MP3（尤其是 VBR）在浏览器里跳转不精确**，建议转成 m4a 或 CBR。
- **单词发音**：从原音频截出的片段有连读，边界误差在几十到一百多毫秒；标准发音用 TTS。

来源：[WhisperX](https://github.com/m-bain/whisperX)、[Qwen3-ASR](https://github.com/QwenLM/Qwen3-ASR)、[ctc-forced-aligner](https://github.com/MahmoudAshraf97/ctc-forced-aligner)、[ECDICT](https://github.com/skywind3000/ECDICT)、[剑桥 B1 词表](https://www.cambridgeenglish.org/Images/506887-b1-preliminary-vocabulary-list.pdf)、[CEFR-J](http://www.cefr-j.org/download_eng)

## 五、课程设计的依据（2026-09-26 补，为 `docs/course.md` 出方案查的）

1. **Nation 四股线**：均衡的语言课由四股大致等量编织——意义输入（泛听泛读）、意义输出（说写）、语言点学习（词汇语法发音）、**流畅性发展（用已懂的材料练快练顺）**。对应到本课：泛听攒量、精听补断点、生词连读聚焦、原速复听。Nation, "The four strands", *Innovation in Language Learning and Teaching* 2007；*What Should Every EFL Teacher Know?*（2013）。[原文 PDF](https://www.scribd.com/doc/293691230/Four-Strands-Paul-Nation)
2. **元认知听力循环的完整序列**：Vandergrift & Goh（*Teaching and Learning Second Language Listening: Metacognition in Action*, 2012）：①听前预测、激活图式 ②第一遍听验证预测 ③第二遍听补漏 ④对照文字找差异、再听 ⑤反思断在哪、哪招有用。弱学习者获益最大（Vandergrift & Tafaghodtari 2010，已录三.7）。`docs/course.md` 的六步闭环就是它加练习与复盘。
3. **窄听**：反复听同一说话人、同一话题的短系列，重复出现的词汇和风格让输入好处理，对中级学习者尤其合适。Krashen, "The case for narrow listening", *System* 24(1), 1996。[免费全文](http://sdkrashen.com/content/articles/the_case_for_narrow_listening.pdf)
4. **泛听的操作参数**（Renandya & Farrell 2011，三.8 的展开）：材料听一遍就懂八九成；量大；学生自己选；听懂大意即可，不抠细节、不预教词汇、听完不测验。
5. **流畅性一股在听力上的形态**：把已理解的材料原速再听——Nation 四股线里流畅性的定义就是「容易、熟悉、关注意思的活动重复做」；重复听也是 Chang & Read（2006，三.5）量出来第二有效的听前支持。
