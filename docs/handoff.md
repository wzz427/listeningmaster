# 交接 —— 现在在哪、上一段为什么这么改

> 答什么：现在在哪 · 上一段为什么这么改 · 下一步从哪接。开机第二件事读（第一件是 `debts.md`）；压缩前写。
> 怎么变短：一批做完整批搬进 `history/`，不逐行削、不设行数硬顶。
> 不许写「还剩几件」—— 那归 `debts.md`。每条只留结论 + 下一步 + 去哪看全文。

## 现在在哪（最新在上）

### 2026-09-12 · 起步：定方向、搭仓库、验证语音识别

- 做了什么 / 为什么这么改：
  - 和 owner 讨论清楚了产品方向，结论落在 `demand.md` 和 `docs/decisions.md`；竞品和听力教学研究的调研结论落在 `docs/research.md`。
  - 按《AI 编程项目管理指南》搭了仓库骨架（`CLAUDE.md`、`demand.md`、`docs/`、`specs/`、`.claude/commands/`），原来的 `260821/` 移到 `materials/260821/`，owner 给的调用文档存成 `docs/refs/qwen-asr-api.md`。
  - 验证了核心不确定环节：用百炼 `qwen-audio-3.0-asr-flash-filetrans` 识别样本音频并与讲稿对齐，产出 `lessons/260821/timeline.json` 和 `align_report.md`。结论写在 `specs/SPEC-001-player.md` 的实验一节：时间轴可用，说话人得用讲稿的（模型的分离不可用）。
  - 备课程序现在有四个文件：`pipeline/keys.py` 读密钥、`pipeline/audio.py` 转音频、`pipeline/asr_probe.py` 调识别、`pipeline/align.py` 对齐讲稿。
- 下一步从哪接：owner 回答 `specs/SPEC-001-player.md` 文末四个问题 → 定稿 → 写播放器。

## 等 owner 亲手做的（一行一件）

- [ ] 回答 SPEC-001 文末四个问题 —— 都是产品方向，不能替他定
- [ ] 决定要不要在百炼后台重置千问密钥 —— 它在 2026-09-12 的对话里被打印过一次（见 `docs/lessons.md`）
- [ ] 考虑把 `api-keys.txt` 移到仓库外面 —— 现在靠 `.gitignore` 挡着，移出去更稳
