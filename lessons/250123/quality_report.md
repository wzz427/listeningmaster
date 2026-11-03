# 切割质量报告 · 250123

引擎 slicing/1.0.0（SPEC-012）。低于线先查讲稿和录音是不是同一版，再查机器耳朵有没有被限流。

- **对上率**：836/997（84%）——红线 80%
- **首末词通过率**（机器耳朵）：正文 59 句，第一个词听到的 55/59（93%）、最后一个词听到的 55/59（93%）
- **边界挪动**：精修句首中位 -80 毫秒（最远 170）、句末中位 -70 毫秒（最远 120）——超过 200 毫秒查精修搜索范围；机器耳朵另挪 38 处（上限 600 毫秒）
- **疑点句**（要人耳抽查）：机器挪到头也没听到的 3 处、照人耳确认改的 0 处、照人定说话人改的 5 处
- 机器耳朵缓存：新听 0 段、现成 116 段
  - 第 17 句开头「Listen as Adam Chandler, author of the b…」，机器听到「as adam chandler author of the book driv」
  - 第 50 句结尾「Once again, our six minutes are up but w…」，机器听到「once again our six minutes are up but wh」
  - 第 59 句结尾「Find the」，机器听到「find the series」

（这页是汇总；细账在 align_report.md、bounds_report.md、ear_report.md。）
