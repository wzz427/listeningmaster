# listening.app 上线手册（阿里云轻量服务器）

> 答什么：把对外版发布到 `listening.app.bayescode.com`（39.105.73.114）的完整操作——装代码、铺公共课库、起服务、接 Caddy、验证、日常运维。谁读：claude 部署时照着做；owner 想看自己那几步（DNS、发网址）也读这份。
> 状态：2026-10-26 随免登录版（v7）更新：访客直接听公共课库、域名从 listen-app 改 listening.app；**先本地验收版（owner 双击 `start-hosted.bat`）确认后才按本手册动服务器**（D54）。规格出处 `specs/SPEC-009-hosted-trial.md` R10 到 R14。
> 密钥规矩：本手册**一个密钥都不含**。SSH 账号、服务器密码见 `docs/refs/阿里云配置指南.md`（它永不入库）；模型密钥用仓库根的 `api-keys.txt` 原样拷过去。

## 红线（先读）

- **上线动作**：owner 本地验收说过之后才动服务器；网址发出去访客就能听（不需要邀请码），邀请码只发给要上传材料的熟人（SPEC-009 R13、D53）。
- **花钱的一步**：第一次在服务器上备真材料会调百炼识别和 DeepSeek（几毛钱一集），跑之前跟 owner 说一声。
- **不碰别人的站**：这台机器上还跑着 TinkerCode 的回滚备胎和课程官网。改 Caddy 前先拉回留底 diff（指南坑⑦）；其它一概不动。
- 服务器上三个文件永不入库、不外发：`api-keys.txt`、`server-config.json`、`server-data/`（各家资料库＋公共课库）。**各家账号里的材料不进公共库**（R14 红线）。

## 前提

| 要什么 | 谁给 | 备注 |
|---|---|---|
| 机器 39.105.73.114 的 SSH | 指南 | 轻量 2核4G，root 登录 |
| Python ≥ 3.10 | 服务器自带 | `python3 --version` 先看一眼；serve.py/accounts.py 用了 `X \| Y` 类型写法 |
| DNS 控制台 | owner | 第 6 步加 A 记录 |
| 发音词典 | 开发机 `..\WordsAudio\`（587MB） | 和仓库并排；服务器上也并排放 |

## 1. 上代码

从开发机（Git Bash）打包传过去。**必须带 `-c core.autocrlf=false`**：不然 Git 在 Windows 上把文本文件换行改成 CRLF，`.service`、`.conf` 在 Linux 上会出鬼（指南坑⑧）。

```bash
git -c core.autocrlf=false archive --format=tar HEAD \
  | ssh root@39.105.73.114 "mkdir -p /opt/listening && tar -x -C /opt/listening"
# 核对传了多少个文件（两边数一样才对）
git ls-tree -r HEAD --name-only | wc -l
ssh root@39.105.73.114 "cd /opt/listening && find . -type f | wc -l"
```

发音词典并排放（`tts.py` 按「仓库旁边找 `../WordsAudio`」取，备课拷词的朗读用）：

```bash
cd .. && tar -cf - WordsAudio | ssh root@39.105.73.114 "tar -x -f - -C /opt/"
```

密钥和配置（都不在 archive 里，单独放）。**`bind` 必须写 `"0.0.0.0"`**：那台机器的 Caddy 在 docker 容器里，容器经网桥 172.18.0.1 来连宿主机，服务只绑 127.0.0.1 的话够不着（2026-09-28 实测踩的）；对外仍只靠轻量防火墙放行 80/443/22。

```bash
scp api-keys.txt root@39.105.73.114:/opt/listening/
ssh root@39.105.73.114
  cd /opt/listening
  cp deploy/server-config.example.json server-config.json
  vi server-config.json        # invite 改成真邀请码；加 "bind": "0.0.0.0"；secure_cookie 保持 true
  chmod 600 api-keys.txt server-config.json
  useradd --system --home /opt/listening --shell /usr/sbin/nologin listen
  chown -R listen:listen /opt/listening /opt/WordsAudio
```

## 1b. 铺公共课库（访客听的就是它，SPEC-009 R14）

访客不登录，听到的是 `server-data/shared/lessons/` 里的课。第一课《咖啡》2026-09-28 部署验证时已经备好在 deploy-check 账号里，拷出来就行：

```bash
ssh root@39.105.73.114
  cd /opt/listening
  mkdir -p server-data/shared/lessons
  cp -r server-data/*/lessons/260821 server-data/shared/lessons/    # 只有一个账号有这课（deploy-check）
  chown -R listen:listen server-data
  cat server-data/shared/lessons/260821/lesson.json | head -5      # 核对：title 是 Coffee
```

以后往公共库加课＝把备好的课目录拷进 `shared/lessons/`，不用改代码；**只放 owner 拍板可公开的课**（D51：仓库里的 BBC 素材定位 sample 可以公开；各家账号上传的材料永远不进公共区）。

## 2. Python 环境

服务器是 Ubuntu 22.04 / Python 3.10（够用；numpy 装到 2.2.6，见 `requirements.txt` 注释）。

```bash
cd /opt/listening
python3 -m venv venv          # 报 ensurepip 缺失就先 apt-get install -y python3.10-venv
venv/bin/pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
```

ffmpeg 不用 apt 装：`imageio-ffmpeg` 自带一个静态的，备课第一步用的就是它。

前台烟测（不花钱、不起服务）：用 `listen` 账号跑一下，匿名就能看到公共库，Ctrl+C 停掉。

```bash
sudo -u listen /opt/listening/venv/bin/python pipeline/serve.py --hosted
# 另开一个终端（都是匿名，不用登录）：
#   curl http://127.0.0.1:8790/login            → 登录页的 HTML（给已有账号的人）
#   curl http://127.0.0.1:8790/api/library      → {"user":null,...,"lessons":[Coffee 那条]}
```

## 3. systemd 常驻

```bash
cp /opt/listening/deploy/listening.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now listening
systemctl status listening            # active (running)
curl -s http://127.0.0.1:8790/api/version    # "copy":"hosted"
journalctl -u listening -f           # 日志在这里（journald 自带轮转，指南坑⑩不用踩）
```

## 4. Caddy 换站点块（这台机器的 Caddy 是 docker 容器，不是系统服务）

2026-09-28 实况：Caddy 跑在容器 `deploy-caddy-1` 里（带着 TinkerCode 备胎栈 gateway/redis），占着 80/443；Caddyfile 在**宿主机** `/opt/tinkercode/deploy/Caddyfile`（只读挂进容器），上面有老域名、api、admin、bayescourse 四个块和 2026-09-28 加的 `listen-app.bayescode.com` 块——bayescourse 是活着的课程官网。

```bash
# ① 留底（坑⑦）
ssh root@39.105.73.114 "cp /opt/tinkercode/deploy/Caddyfile /opt/tinkercode/deploy/Caddyfile.backup-<日期>"
# ② 把旧 listen-app.bayescode.com 块整个删掉，换成 deploy/caddy-listen-app.conf 里的
#    listening.app.bayescode.com 块（reverse_proxy 172.18.0.1:8790——容器里的 127.0.0.1 不是宿主机）
# ③ 让容器优雅重载（不停机、不碰别的容器）：
ssh root@39.105.73.114 "docker exec deploy-caddy-1 caddy reload --config /etc/caddy/Caddyfile"
# ④ 验证：docker ps 三个容器都 Up/healthy；https://bayescourse.gewucode.cn 还是 200
```

证书不用管：DNS 指过来后 Caddy 自己签（几分钟内）；DNS 没指之前它会反复试、日志里报挑战失败，无害。旧域名从未公开发布过，删掉即可、不留跳转。

## 5. DNS（owner 在阿里云控制台做）

加一条 A 记录：`listening.app.bayescode.com` → `39.105.73.114`（各应用统一挂 app.bayescode.com 下，D53）。生效几分钟到半小时；顺手可把旧 `listen-app` 的记录删掉。

## 6. 验证清单（从免费到花钱，按顺序）

| # | 验什么 | 怎么验 | 规格出处 |
|---|---|---|---|
| 1 | 站开得起来、不被收录 | `curl -I https://listening.app.bayescode.com` → 303 到 /web/ 且有 `X-Robots-Tag: noindex` | A64 |
| 2 | **访客不登录直接听** | 无痕窗口打开网址：侧边栏见《咖啡》、点开能播、点词出讲解；界面上没有上传按钮，底部有「登录」 | A62、A69 |
| 3 | 访客碰不到账号里的材料 | 匿名直接 POST `/api/upload` → 401；拿账号里的课名拼 URL 匿名打不开 | A72、A78 |
| 4 | 锁标正常 | 浏览器地址栏 HTTPS 锁标 | A68 |
| 5 | 注册要邀请码、错码进不来 | 从侧边栏「登录」进注册页走一遍 | A72 |
| 6 | 新账号空库待机、上传不自动备课 | 传一集 mp3，资料库里是带「备课」按钮的材料 | A73、A75 |
| 7 | **真材料备课六步（花钱，先跟 owner 说）** | 传 BBC 一集 mp3＋讲稿文件（TXT/PDF/MD），点「备课」，几分钟后变课、能播、点词能查 | A76、A70 |
| 8 | 两个账号互相看不见 | 注册第二个账号，看不到第一个的课；但公共库的课都看得到 | A73 |
| 9 | 学习记录刷新还在 | 听几句刷新，进度点还是半满 | A71 |
| 10 | 带宽 | 同时开几个标签听；卡到受不了记下来（顶约 15 路，R9 迁移触发） | 观察 |

服务器上还能跑一遍自动检查做回归（要先装 playwright＋chromium，可选）：

```bash
cd /opt/listening && sudo -u listen venv/bin/python tests/test_player.py --lesson <刚备好的课名>
```

## 7. 日常运维

- **看日志**：`journalctl -u listening -f`。备课卡在哪：看 `server-data/<账号id>/materials/<材料id>/meta.json` 的 `state` 和 `failed_step`；备课台（诊断现场）在仓库的 `materials/`、`lessons/` 下，失败不拆。
- **重启**：`systemctl restart listening`（在线用户的会话不丢，会话落盘）。
- **更新代码**：停服 → 打包覆盖 → 起服。`api-keys.txt`、`server-config.json`、`server-data/`、`venv/` 都不在包里，不会被覆盖。
  ```bash
  ssh root@39.105.73.114 "systemctl stop listening"
  git -c core.autocrlf=false archive --format=tar HEAD | ssh root@39.105.73.114 "tar -x -C /opt/listening"
  ssh root@39.105.73.114 "systemctl start listening"
  ```
  页面那边不用做更新机制：对外版一刷新就是新的（R4）。
- **备份**：`server-data/` 是各家自己上传的资料库＋公共课库（`shared/`），丢了无法重建。定期 `tar -czf server-data-$(date +%F).tar.gz server-data/` 拉回开发机一份。
- **找回密码**：没有自助（SPEC-009 不做），家长找 owner、owner 转给 claude：在服务器上用 `pipeline/accounts.py` 的存法给该邮箱重写一条密码哈希（PBKDF2，照 `register` 的写法生成），顺手清掉它的旧会话。
- **下线/回滚**：`systemctl stop listening` 即下线；要连域名一起撤，把 Caddy 里 listening.app 那个站点块删掉 reload。代码回滚用留底的 `Caddyfile.backup-*` 和上一版 archive。

## 8. 迁移（不急，写在这备忘）

并发经常接近 15 路、或家长超过约 20 家 → 迁 ECS，照 `docs/refs/阿里云配置指南.md` §4 的从零搭机手册；这台轻量上的东西整体搬（代码、词典、server-data、Caddy 块）。
