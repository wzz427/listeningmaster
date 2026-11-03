# 切割质量报告 · 250918

引擎 slicing/1.0.0（SPEC-012）。低于线先查讲稿和录音是不是同一版，再查机器耳朵有没有被限流。

- **对上率**：894/1038（86%）——红线 80%
- **首末词通过率**（机器耳朵）：正文 62 句，第一个词听到的 57/62（92%）、最后一个词听到的 53/62（85%）
- **边界挪动**：精修句首中位 -80 毫秒（最远 160）、句末中位 -60 毫秒（最远 110）——超过 200 毫秒查精修搜索范围；机器耳朵另挪 44 处（上限 600 毫秒）
- **疑点句**（要人耳抽查）：机器挪到头也没听到的 4 处、照人耳确认改的 0 处、照人定说话人改的 0 处
- 机器耳朵缓存：新听 0 段、现成 192 段
  - 第 21 句结尾「Well, we'll find out the answer later in…」，机器听到「well we'll find out the answer later in 」
  - 第 40 句结尾「Abby」，机器听到「big」
  - 第 43 句结尾「Abby」，机器听到「abby also」
  - 第 61 句结尾「If you've enjoyed this episode, then hea…」，机器听到「if you've enjoyed this episode then head」

（这页是汇总；细账在 align_report.md、bounds_report.md、ear_report.md。）
