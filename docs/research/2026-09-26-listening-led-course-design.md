# 调研报告：以听力为牵引的课程设计

> 答什么：把「在按句播放器的基础上做一门以听力为牵引的英语课」的教学研究依据查清楚，供课程方案 `docs/listening-led-course.md` 引用。
> 谁何时读：改课程方案、写预习／练习／复盘的规格前读。摘要和更早的调研在 `docs/research/2026-09-12-products-teaching-tech-survey.md`。
> 状态：2026-09-26 初版（claude）。方法：网络调研；一手来源尽量给链接。证据强度不一，弱证据在文中标明，引用前先看「证据强度说明」。

## 一、要回答的问题

1. 学生「看得懂、听不懂」，断在哪一步？
2. 一门以听力为主的课，结构上该包含哪几股？
3. 一集材料怎么用最有效（听前、听中、听后）？
4. 材料怎么选、节奏怎么排？
5. 练习出什么、怎么出？
6. 别的产品把「听」组织成课，做到了哪一步、缺什么？

## 二、学生的问题：断在解码

**Field 的两步模型**：听懂分两步——先把**声音解码成词**（decoding），再把**词拼成意思**（meaning building）。听力教学不该只核对答案，该先诊断理解断在哪一步，再用短片段听写、音素辨别这类小练习去补断的那一步（Field, *Listening in the Language Classroom*, CUP 2008）。

**Goh (2000) 的证据**：访谈 40 名华语背景学习者，一半的听力问题出在感知层面，最典型的就是「认识的词听不出来」，水平越低越严重（[ERIC](https://eric.ed.gov/?id=EJ601557)）。这正是我们学生（读得懂、听不懂）的画像：第二步没问题，断在第一步。

**对本课的含义**：训练重心是让耳朵认出眼睛早已认识的词；诊断材料不用额外收集——学生在哪句重听、看了文字、点了词，就是断点记录（已落实在播放器的学习记录）。

## 三、课的结构：四股线

**Nation 的四股线**：一门均衡的语言课应由四股大致等量（各约四分之一）编织（Nation, "The four strands", *Innovation in Language Learning and Teaching* 2007；*What Should Every EFL Teacher Know?* 2013。[原文 PDF](https://www.scribd.com/doc/293691230/Four-Strands-Paul-Nation)）：

| 股 | 内容 | 在本课的形态 |
|---|---|---|
| 意义输入 | 听读大量可理解材料，关注内容本身 | 整段盲听、原速复听 |
| 意义输出 | 为交流而说写 | 以后（跟读、复述） |
| 语言点学习 | 直接学词汇、语法、发音、连读 | 生词点讲、逐句精听 |
| 流畅性发展 | 用**已懂**的材料练快练顺 | 精听完的原速复听 |

**要点**：四股是编织关系，不是先后关系；只做精听（语言点）不做泛听和流畅，课就是失衡的——这是本方案补上「原速复听」和强调「量」的依据。

## 四、一集的教学序列：元认知循环

**Vandergrift & Goh 的教学序列**（*Teaching and Learning Second Language Listening: Metacognition in Action*, 2012）：①听前预测、激活图式 → ②第一遍听、验证预测 → ③第二遍听、补漏 → ④对照文字找差异、再听 → ⑤反思断在哪、哪招有用。

**实证**：这套循环的教学实验里，听力弱的学习者进步显著大于对照组（Vandergrift & Tafaghodtari 2010，见 `docs/research/2026-09-12-products-teaching-tech-survey.md` 三.7）。

**对本课的含义**：我们的六步闭环（预习→盲听→精听→复听→练习→复盘）就是这套循环加练习和复盘：预习承担①，盲听承担②③，精听承担④（逐级提示＋看文字），复盘承担⑤。

## 五、听前：预习怎么做

- **Chang & Read (2006)**：四种听前支持按效果排序——**给话题背景最有效，其次是重复听，先看题再次，预教词汇最没用**（[ERIC](https://eric.ed.gov/?id=EJ753072)）。
- Elkhafaifi (2005)：先看题比先学词效果好。
- 预测任务是元认知循环的起点（见四）。

**结论**：预习 = 话题背景 + 两个预测问题 + 少量关键词，重点放在「这些词在录音里听起来什么样」（耳朵预热的不是词义是声音）；不预教一串生词。已定于决策 D5。

## 六、听中：文字（字幕）怎么用

- 看英文字幕对理解和词汇都有明显帮助（Montero Perez 2013 元分析，理解效果量 g=0.99，见 `docs/research/2026-09-12-products-teaching-tech-survey.md` 三.4）。
- **只显示关键词的字幕，效果不比没有字幕好**，学习者还觉得干扰——要给就给整句（决策 D6 的依据）。
- 字幕帮的是理解，不等于练了耳朵：**看完文字必须回原速再听**（决策 D7 的依据）。

## 七、听后：练习与复习

- **听写有效**（Kiany & Shiramiry 2002）；对解码断点，部分听写（只写关键词或半句）比全文听写省时且聚焦。
- **连读、弱读可以显式教**，能提高听力理解；已有研究多是小样本（弱证据，方向可用）。
- 词汇要**放回声音里回收**：点过的词放回原句重听，而不是背词表（Nation 的语言点学习＋复习原理）。
- **影子跟读**对低水平学习者的听力理解有帮助（Hamada 2016）；排在耳朵立住之后，只做录音回放对比、不打分（`demand.md` 明确不做口语评分）。

## 八、量与选材：泛听、窄听

- **泛听的操作参数**（Renandya & Farrell 2011, "Teacher, the tape is too fast!", *ELT Journal*）：材料听一遍就懂八九成；量大；学生自己选；听懂大意即可——不抠细节、不预教词汇、听完不测验。
- **窄听**（Krashen, "The case for narrow listening", *System* 24(1), 1996。[免费全文](http://sdkrashen.com/content/articles/the_case_for_narrow_listening.pdf)）：反复听同一说话人、同一话题的短系列，重复的词汇和风格让输入好处理，对中级学习者尤其合适。后续研究见 [Rodrigo 的音频库实验](https://digitalcommons.kennesaw.edu/cgi/viewcontent.cgi?article=1190&context=dimensions)、[Chang 对窄听的界定](https://core.ac.uk/download/pdf/230363786.pdf)。
- **词汇覆盖**：充分理解大约需要认识 95% 的词（van Zeeland & Schmitt 2013）→ 选材判据：盲听一遍能懂九成上下；先降半级（A2 材料给 B1 边缘的学生）攒解码自动性和信心。

**对本课的含义**：单元 = 同一系列连听 4 到 6 集（Real Easy English 同两位主持人）；一周 2 到 3 集、不贪多；家长建资料库、学生自选，是教学设计的一部分而不是附赠功能。

## 九、动机与坚持

听力是长跑，动机是燃料。研究上的共识（泛听文献＋动机文献）：**自选材料、不测验、看得见的进步**是坚持的前提。对应到本课：材料学生选（D20 的资料库）、不问「懂了没」（D11）、复盘页把进步画成数、原速复听「忽然都听懂了」的即时成就感。

## 十、竞品：他们的「课」是什么

材料取自 `docs/research/2026-09-12-products-teaching-tech-survey.md` 一、二（2026-09-12 调研），这里换成课程视角看：

| 产品 | 它的「课」怎么组织 | 从教学设计看缺什么 |
|---|---|---|
| 可可英语 | 视频精听「4 步法」、单句听写 | 流程是固定的练习形式，不按学生断点调整 |
| 扇贝听力 | 盲听→选词填空→拼写，智能填空、错题集 | 挖空按「重点词」挖，不按「这个人哪里没听出来」挖 |
| 每日英语听力 | 听写、跟读、分重点词提示 | 工具箱齐全，但没有教学序列（预测→验证→修补→反思） |
| Aboboo | 三种复读、分级听写 | 复读机逻辑：练什么由用户自己定 |
| 听点点 | 盲听→双语对照→影子跟读 | 有「先听后看」的意识，无诊断、无卡点积累 |
| Daily Dictation | 听→打字→核对→朗读 | 单一练习形式 |
| LingQ / Migaku | 生词标级、原句挖矿进间隔重复 | 词汇回收做得好，**以读带听**，不是听力牵引 |
| Language Reactor | 双语字幕、逐句回退 | 看剧工具，无课程结构 |

**共同缺口**（也是我们的位置）：没有产品把 AI 用在**诊断「为什么没听出来」**上，也没有一家从**学生自己的卡点记录**出练习。练习都是从「重点词／固定流程」出的，教学序列（元认知循环）和结构均衡（四股线）没人做。

## 十一、证据强度说明

- 强（元分析、多组对照）：字幕的作用、元认知循环教学、听写、泛听参数。
- 中（有对照但样本有限）：预教词汇无效、窄听、影子跟读、词汇覆盖率阈值。
- 弱（小样本或自述）：连读显式教学的具体效果量、各竞品「AI 出题」的真实质量（未核实）。
- 引用规则：弱证据只用来定方向，不拿来定参数；参数（如一周几集、复听几遍）按中强证据＋学生实际反应调整。

## 十二、结论：十条设计推论

1. 先诊断后训练：断点在解码（二）→ 精听记卡点，练习从卡点出。
2. 四股齐张（三）→ 盲听、复听是「输入＋流畅」，精听、生词是「语言点」，以后跟读是「输出」。
3. 预测先行（四）→ 预习出两个预测问题，盲听带着验证。
4. 背景最有效、预教词最没用（五）→ 预习只给背景＋预测＋3 到 5 个关键词的声音。
5. 文字整句给、看完必回听（六）→ 已落实 D6、D7。
6. 材料要够得着（八）→ 九成判据，先降半级，阶梯上难度。
7. 窄听（八）→ 单元＝同系列 4 到 6 集。
8. 泛听攒量、自选、不测验（八、九）→ 学生主权（D11）、资料库（D20）、一周 2 到 3 集。
9. 听写与词回收（七）→ 课后练习出部分听写、连读听辨、词放回原句。
10. 进步要看得见（九）→ 复盘统计页＋原速复听后自评。

## 十三、参考文献

- Field, J. (2008). *Listening in the Language Classroom*. Cambridge University Press.
- Goh, C. (2000). A cognitive perspective on language learners' listening comprehension problems. [ERIC EJ601557](https://eric.ed.gov/?id=EJ601557)
- Nation, I. S. P. (2007). The four strands. *Innovation in Language Learning and Teaching*, 1(1), 2–12. [PDF](https://www.scribd.com/doc/293691230/Four-Strands-Paul-Nation)；Nation (2013). *What Should Every EFL Teacher Know?* Compass.
- Vandergrift, L. & Goh, C. (2012). *Teaching and Learning Second Language Listening: Metacognition in Action*. Routledge.
- Vandergrift, L. & Tafaghodtari, M. H. (2010). 见 `docs/research/2026-09-12-products-teaching-tech-survey.md` 三.7。
- Chang, A. C.-S. & Read, J. (2006). [ERIC EJ753072](https://eric.ed.gov/?id=EJ753072)
- Elkhafaifi, H. (2005). 见 `docs/research/2026-09-12-products-teaching-tech-survey.md` 三.5。
- Montero Perez, K. et al. (2013; 2014). 见 `docs/research/2026-09-12-products-teaching-tech-survey.md` 三.4。
- van Zeeland, H. & Schmitt, N. (2013). 见 `docs/research/2026-09-12-products-teaching-tech-survey.md` 三.5。
- Kiany, G. R. & Shiramiry, S. (2002). 见 `docs/research/2026-09-12-products-teaching-tech-survey.md` 三.6。
- Hamada, Y. (2016). 见 `docs/research/2026-09-12-products-teaching-tech-survey.md` 三.6。
- Krashen, S. D. (1996). The case for narrow listening. *System*, 24(1), 97–100. [全文](http://sdkrashen.com/content/articles/the_case_for_narrow_listening.pdf)、[ScienceDirect](https://www.sciencedirect.com/science/article/pii/0346251X9500054N)
- Renandya, W. A. & Farrell, T. S. C. (2011). 'Teacher, the tape is too fast!' *ELT Journal*, 65(1).
- Rodrigo, V. 等（窄听后续）：[Kennesaw](https://digitalcommons.kennesaw.edu/cgi/viewcontent.cgi?article=1190&context=dimensions)；Chang（窄听界定）：[CORE](https://core.ac.uk/download/pdf/230363786.pdf)
- 竞品材料：`docs/research/2026-09-12-products-teaching-tech-survey.md` 一、二（2026-09-12 调研，来源链接在彼处）。
