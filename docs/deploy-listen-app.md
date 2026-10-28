# listening.app 上线手册（阿里云 ECS 182.92.206.53，容器形态）

> 答什么：把对外版发布到 `listening.app.bayescode.com`（182.92.206.53）的完整操作——上代码、共享发音词库、起容器、接网关、验证、日常运维、回滚。谁读：claude 部署时照着做；owner 想看自己那几步（验收、发网址）也读这份。
> 状态：2026-10-28 随首次部署改版：机器从轻量 39.105.73.114 换到 BayesCode 统一部署机 182.92.206.53（owner 给了《服务器部署指南》，兄弟软件「羊了个词」已在这台上；`*.app.bayescode.com` 泛解析已指向它，**DNS 一条都不用加**），形态从宿主机 systemd 换成应用容器（网关统一按容器名反代）。首次部署已按本手册完成，见文末发版记录。规格出处 `specs/SPEC-009-hosted-trial.md` R10 到 R14。
> 密钥规矩：本手册**一个密钥都不含**。SSH 钥匙按《服务器部署指南》§7 用 `~/.ssh/tinkercode_deploy`（内容永不入库）；模型密钥用仓库根的 `api-keys.txt` 原样拷过去（600）。

## 红线（先读）

- **上线动作**：owner 本地验收（双击 `start-hosted.bat`）说过之后才动服务器（D54）；网址发不发出去、发给谁，发起权在 owner。邀请码只发给要上传材料的熟人（SPEC-009 R13、D53）。
- **花钱的一步**：服务器上备真材料会调百炼识别和 DeepSeek（几毛钱一集），跑之前跟 owner 说一声。
- **不碰别人的站**：这台机器跑着 TinkerCode 网关栈和羊了个词全家。网关 Caddyfile 改前先备份、改完先 validate 再 reload；羊了个词和别的容器一概不动。
- **compose 项目名**：我们的 compose 必须带 `name: listening`——不写会取目录名 `deploy`，和网关栈、羊了个词撞项目名，`down`/`--remove-orphans` 会把别人的容器当孤儿清掉（2026-10-28 部署时撞见，已修）。
- 服务器上这些永不入库、不外发：`api-keys.txt`、`server-config.json`、`server-data/`（各家资料库＋公共课库）。**各家账号里的材料不进公共库**（R14 红线）。
- 《服务器部署指南》在兄弟软件仓 `SheepAndWord/.ai-local/docs/`（owner 私有区，永不入库、不外传）；本文只写我们这一摊。

## 服务器是什么形状（和 39.105.73.114 不同在哪）

- 一台 ECS 跑 BayesCode 全部应用：**网关 Caddy 是容器 `deploy-caddy-1`**（宿主机配置 `/opt/tinkercode/deploy/Caddyfile` 只读挂进去，占 80/443，证书全自动），各应用容器挂 `deploy_default` 网络，网关按**容器名**反代。
- 我们没有静态容器：整站都要过会话门、音频带账号指路，拆静态层会绕过权限——就一个应用容器 `listeningapp`（镜像 `listening-app:<git短sha>`，跑 `serve.py --hosted`）。
- 共享发音词库根 `/opt/bayescode/audio/`（指南 §4.1）：`base/google_en-GB/`（5 万真人英音，和羊了个词同源）＋ `apps/<应用>/`（各应用补库）。我们备课拷词只读 base 层，挂进容器 `/opt/WordsAudio/google_en-GB`；词典里没有的词点的时候百炼现读、存课里，不写词库。
- 密钥和配置不进镜像（`.dockerignore` 挡着）：宿主机 `/opt/listening/` 下的 `api-keys.txt`、`server-config.json` 以单文件只读挂进容器。

## 1. 上代码、密钥、公共课库

```bash
# 代码（Git Bash；必须带 -c core.autocrlf=false，不然换行变 CRLF 在 Linux 出鬼）
git -c core.autocrlf=false archive --format=tar HEAD \
  | ssh -i ~/.ssh/tinkercode_deploy root@182.92.206.53 "mkdir -p /opt/listening && tar -x -C /opt/listening"
git ls-tree -r HEAD --name-only | wc -l     # 两边数一样才对
ssh -i ~/.ssh/tinkercode_deploy root@182.92.206.53 "cd /opt/listening && find . -type f | wc -l"

# 密钥和配置（先放好再起容器——宿主机没有这个文件的话 Docker 会建出同名目录）
scp -i ~/.ssh/tinkercode_deploy api-keys.txt root@182.92.206.53:/opt/listening/
ssh -i ~/.ssh/tinkercode_deploy root@182.92.206.53   # 照 deploy/server-config.example.json 写
  #   server-config.json：invite 真邀请码、bind 必须 "0.0.0.0"（容器网络）、secure_cookie true
  chmod 600 /opt/listening/api-keys.txt /opt/listening/server-config.json
  mkdir -p /opt/listening/server-data/shared /opt/listening/materials /opt/listening/lessons

# 公共课库（访客听的就是它，只放 owner 拍板可公开的课，R14/D51）
cd server-data/shared && tar -cf - lessons \
  | ssh -i ~/.ssh/tinkercode_deploy root@182.92.206.53 "tar -x -f - -C /opt/listening/server-data/shared"
```

发音词典**不用传**：服务器上已有（羊了个词先铺的），第一次部署时已按指南 §4.1 落位共享根：
`cp -al /opt/sheep-and-word/audio/google_en-GB /opt/bayescode/audio/base/google_en-GB`（硬链接，不占新空间）。

## 2. 建镜像、起容器

```bash
ssh -i ~/.ssh/tinkercode_deploy root@182.92.206.53
cd /opt/listening
docker build -f deploy/Dockerfile -t listening-app:$(git 不在服务器上，用开发机的 git 短 sha) .   # 例 listening-app:934f5488
sed -i "s/:TAG/:<同一个sha>/" deploy/docker-compose.yml
docker compose -f deploy/docker-compose.yml config --quiet   # 配置没毛病再起
docker compose -f deploy/docker-compose.yml up -d
docker ps --filter name=listeningapp     # Up 才算数
# 内部烟测（网关容器按容器名来连，模拟将来网关走的路）：
docker exec deploy-caddy-1 wget -qO- http://listeningapp:8790/api/version   # "copy":"hosted"
```

镜像是代码＋依赖（`requirements.txt`）定死的；账号数据、备课台、密钥、配置、发音词典全是挂载卷——升级换镜像、数据不动。

## 3. 网关加站点块

```bash
ssh -i ~/.ssh/tinkercode_deploy root@182.92.206.53
cp /opt/tinkercode/deploy/Caddyfile /opt/tinkercode/deploy/Caddyfile.bak-$(date +%Y%m%d)-<原因>
vim /opt/tinkercode/deploy/Caddyfile     # 文末追加 deploy/caddy-listen-app.conf 里的块
docker exec deploy-caddy-1 caddy validate --config /etc/caddy/Caddyfile   # 必过才 reload
docker exec deploy-caddy-1 caddy reload  --config /etc/caddy/Caddyfile
```

块内容（也存了一份在仓库 `deploy/caddy-listen-app.conf`）：`listening.app.bayescode.com { encode zstd gzip; reverse_proxy listeningapp:8790 }`。证书自动签：**新域名首签要几十秒**，这期间 curl 连不上不是挂了，等等再试。DNS 不用动（泛解析已指这台）。

## 4. 验证清单（从免费到花钱，按顺序）

| # | 验什么 | 怎么验 | 2026-10-28 结果 |
|---|---|---|---|
| 1 | 站开得起来、不被收录 | `curl -I https://listening.app.bayescode.com` → 303 到 /web/ 且有 `X-Robots-Tag: noindex` | ✅ |
| 2 | **访客不登录直接听** | 无痕窗口打开：侧边栏四集、点开能播、点词出讲解；界面没有上传按钮、底部有「登录」 | ✅（Playwright 无头：真播放 26.5s→29.5s、零 JS 报错） |
| 3 | **密钥和配置摸不到** | 匿名/登录 GET＋HEAD `/api-keys.txt`、`/server-config.json`、`/server-data/`、`/materials/`、`/pipeline/*` → 全 404（2026-10-28 堵的洞，serve.py GET/HEAD 白名单） | ✅ |
| 4 | 访客碰不到账号里的材料 | 匿名 POST `/api/upload` → 401；拿账号里的课名拼 URL 匿名打不开 | ✅（401 实测；课名指路是老检查，hosted 测试 29 项盖着） |
| 5 | 注册要邀请码、错码进不来 | 从侧边栏「登录」进注册页走一遍 | ✅（curl：错码「邀请码不对」、对码发 Secure+HttpOnly 会话） |
| 6 | 音频拖动 | `curl -H "Range: bytes=100-200" …/lessons/260821/audio.m4a` → 206 | ✅ |
| 7 | 登录态会话 | 注册/登录后 `/api/library` 的 `user` 是邮箱、自己的课和公共课都在 | ✅（探针账号 deploy-probe@bayescode.local） |
| 8 | **真材料备课六步（花钱，先跟 owner 说）** | 传一集 mp3＋讲稿，点「备课」，几分钟后变课、能播、点词能查 | 首次部署没跑（四集是开发机备好传的）；下次有新材料时在服务器上首跑 |
| 9 | 兄弟站无恙 | `curl -I https://sheep-and-word.app.bayescode.com` → 200 | ✅ |

真浏览器全流程回归（不花钱）：开发机 `<pywork python>` 跑一份打生产站的 Playwright 检查（本次用的脚本存过 `C:\Users\wzzpk\AppData\Local\Temp\prod_play_check.py` 的形状：进站→侧边栏四集→Escape 收起→播《Coffee》→currentTime 前进→零报错）。

## 5. 日常运维

- **看日志**：`docker logs -f listeningapp`（json-file 自带 20m×3 轮转）。备课卡在哪：看 `server-data/<账号id>/materials/<材料id>/meta.json` 的 `state` 和 `failed_step`；备课台（诊断现场）在 `/opt/listening/materials/`、`/opt/listening/lessons/`，失败不拆。
- **重启**：`docker restart listeningapp`（会话落盘，在线用户不掉线）。
- **更新代码**（页面那边不用做更新机制，刷新就是新的，R4）：
  ```bash
  git -c core.autocrlf=false archive --format=tar HEAD | ssh -i ~/.ssh/tinkercode_deploy root@182.92.206.53 "tar -x -C /opt/listening"
  ssh -i ~/.ssh/tinkercode_deploy root@182.92.206.53 \
    "cd /opt/listening && docker build -f deploy/Dockerfile -t listening-app:<新sha> . \
     && sed -i 's/:listening-app:[0-9a-f]*/:listening-app:<新sha>/' deploy/docker-compose.yml \
     && docker compose -f deploy/docker-compose.yml up -d"
  ```
  `api-keys.txt`、`server-config.json`、`server-data/`、`materials/`、`lessons/` 都不在镜像里，覆盖代码不影响它们。
- **备份**：`server-data/` 是各家上传的资料库＋公共课库，丢了无法重建。定期打包拉回开发机：`ssh … 'cd /opt/listening && tar -czf - server-data' > server-data-$(date +%F).tar.gz`。
- **找回密码**：没有自助（SPEC-009 不做），家长找 owner、owner 转给 claude：照 `pipeline/accounts.py` 的 `register` 写法生成 PBKDF2 哈希，在服务器 `server-data/accounts.json` 里重写该邮箱那条，顺手清它的旧会话。
- **换邀请码**：改 `/opt/listening/server-config.json` 的 `invite` 后 `docker restart listeningapp`。

## 6. 回滚

| 出问题的层 | 回滚动作 |
|---|---|
| 应用（代码） | `sed` 把 compose 里的 tag 换回旧镜像 tag → `docker compose -f deploy/docker-compose.yml up -d`（旧镜像别删就有得回；数据卷不动） |
| 网关配置 | `cp /opt/tinkercode/deploy/Caddyfile.bak-<…> /opt/tinkercode/deploy/Caddyfile && docker exec deploy-caddy-1 caddy validate --config /etc/caddy/Caddyfile && … caddy reload …` |
| 下线整站 | 网关 Caddyfile 里删掉 listening 那个站点块 reload（域名就 404 了）；容器留着 `docker stop listeningapp` 也行 |

## 7. 发版记录

| 时间 | 操作人 | Commit | 镜像 tag / 回滚点 | 结论 |
|---|---|---|---|---|
| 2026-10-28 | claude（owner 下指令部署） | `934f5488` | `listening-app:934f5488`；网关备份 `Caddyfile.bak-20261028-add-listening` | 首次部署。验证清单 1-7、9 全过（第 8 项真材料备课留到下次）；同批堵了密钥泄露洞（对外模式 GET/HEAD 白名单），hosted 29 项全绿 |
| 2026-09-28 | claude | （旧机 39.105.73.114 的部署，随换机作废） | 旧机 systemd 形态；机器已被 182.92.206.53 取代 | 旧机服务还在跑旧代码（含已堵的洞，域名从未公开）；**等 owner 发话再下线** |

## 8. 旧机器（39.105.73.114）处置

统一部署机定了 182.92.206.53 后旧机作废：上面还有 2026-09-28 部署的 systemd 版 `listening` 服务和 `/opt/listening`、`/opt/WordsAudio`。旧域名 `listen-app.bayescode.com` 的 DNS owner 已说可删。**下线动作（`systemctl disable --now listening`＋清目录）等 owner 发话再做**——那台还跑着别人的站，不急不动。
