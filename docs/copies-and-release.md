# 三版管理与发版 —— 开发版、体验版、正式版怎么管、怎么操作

> 答什么：三个住处一套代码——每份在哪、谁用、跑哪一版、数据归谁；从改代码到上线的完整操作：交版、owner 点「更新」、验完说「上」、发版、出问题退回；密钥和配置怎么同步。规则本身（为什么这么定、怎么验收）在 `specs/SPEC-008-stable-and-dev.md`（决策 D55）；服务器上的细节（命令、验证清单、回滚）在 `docs/deploy-listen-app.md`。
> 谁何时读：任何会话动手改代码之前——先知道改哪份、别碰哪份；每次要交版、要上线、体验版或线上出了问题的时候。这是开机三步之外的第一份操作手册。

## 三个住处，一套代码（D55）

| | 在哪 | 谁用 | 跑的是哪一版 | 账号、上传的材料 |
|---|---|---|---|---|
| 开发版 | 本机的仓库目录（claude 改的那份） | claude | 随时最新，可能改到一半 | 本机 `server-data/`（测试用） |
| 体验版 | 旁边的 `ListeningMaster-stable`（git worktree，**一个字不手改**） | owner 测新版本 | claude 钉住、owner 点过「更新」的那一版 | 自己一份 `server-data/`（不进仓库） |
| 正式版 | 线上 https://listening.app.bayescode.com （182.92.206.53 容器） | 孩子和各家 | owner 在体验版上验过、说「上」的那一版 | 服务器的 `server-data/` |

入口：开发版和体验版根上都有 `start-trial.bat`（双击开体验版网站，http://localhost:8790/ ，两边双击哪个都进体验版）；口语实验页 `start-speak-lab.bat` 与三版无关。claude 自己看效果：网站 `<pywork python> pipeline/serve.py --hosted`（8791，公共课就是仓库里的课）、播放器 `<pywork python> pipeline/serve.py 8766`。开发版不许占 8790（那是体验版的地址，owner 的记录按它存）。

## 日常循环：改 → 测 → 交 → 验 → 上

1. **改**：只改开发版，提交。体验版一个字不手改，换版本只经 `pipeline/stable_copy.py`。
2. **测**：改了播放器或本地服务跑 `tests/test_player.py`；改了网站（serve.py 对外模式、`web/library.js`、`web/login.html`）跑 `tests/test_hosted_frontend.py`——两份全过时各自记下代码指纹，这是交版的前提（少一份都钉不住）。改了句子边界或停法另跑 `tests/test_audio.py`（交版不查这条，靠自己）。
3. **交版**：`<pywork python> pipeline/stable_copy.py invite --what "<一句人话：这一版多了什么>"`（60 字以内，不许带提交号、规格号这类内部词）。钉完体验版页面的「更新」亮起来。
4. **owner 验**：跟他说「可以更新了：多了 X。体验版右上角的『更新』亮了，点一下。」他点后服务停几秒、换到钉住的那一版、页面自己回来停在原来那句，按钮灰回去。`<pywork python> pipeline/stable_copy.py status` 随时看他在哪一版、点了没有、服务开没开。
5. **上线**（他全部确认、亲口说「上」才动）：照 `docs/deploy-listen-app.md` §5——**发的是体验版当前停的那一版**，不是开发版最新的提交；镜像 tag 用那一版的提交短号。上线、发网址给谁，发起权都在 owner。
6. **记账**：发版记进部署手册 §7 的发版记录；欠账表、交接页照节奏动。

## 出问题

- **他反馈新版本有问题**：`<pywork python> pipeline/stable_copy.py rollback` 把上一版钉回去，再请他点「更新」回去；然后在开发版修，重新交版。
- **换版本中途失败**：机制自己退回原来那一版、服务照常起，页面留一句人话（「还是原来那一版，照常能用」）。claude 看 `status` 里「上一次换版本」处理。
- **开发版正做一半、又要修体验版上的问题**：从体验版所在的提交拉临时分支 `git switch -c stable-fix <提交>` → 修 → 测 → 提交 → `invite` → 回 master `git cherry-pick` 这个修复 → 下次正常交版后删掉临时分支。
- **线上出问题**：回滚动作在部署手册 §6（compose 里的 tag 换回旧镜像、数据卷不动；旧镜像别删）。

## 数据与密钥各归各

- 登录、学习记录存在浏览器里、按地址隔离：体验版 localhost:8790 和线上互不相通——给 owner 提前说明，免得误会丢数据。地址不能换，换了记录就看不见。
- 体验版用出来的数据（点词讲解缓存、现读的朗读、上传材料点备课的备课台、注册的账号）都在体验版目录里，换版本自动留下，也不算「被改过」。
- 公共课：体验版直接用这一版仓库里的 `lessons/`（claude 新备的课随版本送，他点了「更新」才出现）；线上铺在服务器 `server-data/shared/lessons/`（部署手册 §1）。
- 密钥 `api-keys.txt` 不进仓库。体验版那份在起服务、换版本时自动从开发版拷（只比字节、不读内容）——owner 换了钥匙只要改开发版根目录这份，双击体验版就跟上；服务器那份照部署手册单独传。

## 换电脑、体验版目录丢了

`<pywork python> pipeline/stable_copy.py setup` 在旁边重建（要求两份测试对当前提交全过）。整目录搬家后 worktree 的绝对指针要修（`docs/lessons.md` 2026-10-25 那条）。完整的从零搭建见 `docs/environment.md`。
