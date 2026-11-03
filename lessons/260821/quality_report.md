# 切割质量报告 · 260821

引擎 slicing/1.0.0（SPEC-012）。低于线先查讲稿和录音是不是同一版，再查机器耳朵有没有被限流。

- **对上率**：725/788（92%）——红线 80%
- **首末词通过率**（机器耳朵）：正文 89 句，第一个词听到的 80/89（90%）、最后一个词听到的 86/89（97%）
- **边界挪动**：精修句首中位 -50 毫秒（最远 170）、句末中位 -60 毫秒（最远 130）——超过 200 毫秒查精修搜索范围；机器耳朵另挪 67 处（上限 600 毫秒）
- **疑点句**（要人耳抽查）：机器挪到头也没听到的 3 处、照人耳确认改的 0 处、照人定说话人改的 0 处
- 机器耳朵缓存：新听 0 段、现成 192 段
  - 第 48 句开头「I have it kind of, I don't know, work ti…」，机器听到「have it kind of i don't know work time n」
  - 第 48 句结尾「I have it kind of, I don't know, work ti…」，机器听到「have it kind of i don't know work time n」
  - 第 76 句开头「Neil, it's time to recap the vocabulary …」，机器听到「it's time to recap the vocabulary we use」

（这页是汇总；细账在 align_report.md、bounds_report.md、ear_report.md。）
