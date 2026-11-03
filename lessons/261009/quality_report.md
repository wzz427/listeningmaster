# 切割质量报告 · 261009

引擎 slicing/1.0.1（SPEC-012）。低于线先查讲稿和录音是不是同一版，再查机器耳朵有没有被限流。

- **对上率**：1059/1072（99%）——红线 80%
- **首末词通过率**（机器耳朵）：正文 77 句，第一个词听到的 74/77（96%）、最后一个词听到的 76/77（99%）
- **边界挪动**：精修句首中位 -55 毫秒（最远 140）、句末中位 -60 毫秒（最远 110）——超过 200 毫秒查精修搜索范围；机器耳朵另挪 58 处（上限 600 毫秒）
- **疑点句**（要人耳抽查）：机器挪到头也没听到的 2 处、照人耳确认改的 0 处、照人定说话人改的 0 处
- 机器耳朵缓存：新听 0 段、现成 105 段
  - 第 9 句开头「Uh, Now I told you I watched a film last…」，机器听到「now i told you i watched a film last nig」
  - 第 63 句结尾「I wouldn't go to the cinema to watch a r…」，机器听到「i wouldn't go to the cinema to watch a r」

（这页是汇总；细账在 align_report.md、bounds_report.md、ear_report.md。）
