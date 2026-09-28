# listen-app 上线手册（阿里云轻量服务器）

> 答什么：把对外版发布到 `listen-app.bayescode.com`（39.105.73.114）的完整操作——装代码、起服务、接 Caddy、验证、日常运维。谁读：claude 部署时照着做；owner 想看自己那几步（DNS、发网址）也读这份。
> 状态：2026-09-28 写好待用（代码全绿、未上过服务器）。规格出处 `specs/SPEC-009-hosted-trial.md` R10 到 R13。
> 密钥规矩：本手册**一个密钥都不含**。SSH 账号、服务器密码见 `docs/refs/阿里云配置指南.md`（它永不入库）；模型密钥用仓库根的 `api-keys.txt` 原样拷过去。

## 红线（先读）

- **上线动作**：一切就绪、owner 亲口说「上」，才把网址和邀请码发出去（SPEC-009 R13）。
- **花钱的一步**：第一次在服务器上备真材料会调百炼识别和 DeepSeek（几毛钱一集），跑之前跟 owner 说一声。
- **不碰别人的站**：这台机器上还跑着 TinkerCode 的回滚备胎和课程官网。Caddy 只**追加**站点块、改前先拉回 diff（指南坑⑦）；其它一概不动。
- 服务器上三个文件永不入库、不外发：`api-keys.txt`、`server-config.json`、`server-data/`（各家资料库）。

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

## 2. Python 环境

服务器是 Ubuntu 22.04 / Python 3.10（够用；numpy 装到 2.2.6，见 `requirements.txt` 注释）。

```bash
cd /opt/listening
python3 -m venv venv          # 报 ensurepip 缺失就先 apt-get install -y python3.10-venv
venv/bin/pip install -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt
```

ffmpeg 不用 apt 装：`imageio-ffmpeg` 自带一个静态的，备课第一步用的就是它。

前台烟测（不花钱、不起服务）：用 `listen` 账号跑一下，能看到登录页就行，Ctrl+C 停掉。

```bash
sudo -u listen /opt/listening/venv/bin/python pipeline/serve.py --hosted
# 另开一个终端：curl http://127.0.0.1:8790/login   → 出登录页的 HTML
```

## 3. systemd 常驻

```bash
cp /opt/listening/deploy/listening.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now listening
systemctl status listening            # active (running)
curl -s http://127.0.0.1:8790/api/version    # "copy":"hosted"
journalctl -u listening -f           # 日志在这里（journald 自带轮转，指南坑⑩不用踩）
```

## 4. Caddy 加站点块（这台机器的 Caddy 是 docker 容器，不是系统服务）

2026-09-28 实况：Caddy 跑在容器 `deploy-caddy-1` 里（带着 TinkerCode 备胎栈 gateway/redis），占着 80/443；Caddyfile 在**宿主机** `/opt/tinkercode/deploy/Caddyfile`（只读挂进容器），上面已有老域名、api、admin、bayescourse 四个块——bayescourse 是活着的课程官网。

```bash
# ① 留底（坑⑦）
ssh root@39.105.73.114 "cp /opt/tinkercode/deploy/Caddyfile /opt/tinkercode/deploy/Caddyfile.backup-<日期>"
# ② 把 deploy/caddy-listen-app.conf 里的站点块追加到那份 Caddyfile 末尾（reverse_proxy 172.18.0.1:8790——容器里的 127.0.0.1 不是宿主机）
# ③ 让容器优雅重载（不停机、不碰别的容器）：
ssh root@39.105.73.114 "docker exec deploy-caddy-1 caddy reload --config /etc/caddy/Caddyfile"
# ④ 验证：docker ps 三个容器都 Up/healthy；https://bayescourse.gewucode.cn 还是 200
```

证书不用管：DNS 指过来后 Caddy 自己签（几分钟内）；DNS 没指之前它会反复试、日志里报挑战失败，无害。

## 5. DNS（owner 在阿里云控制台做）

加一条 A 记录：`listen-app.bayescode.com` → `39.105.73.114`。生效几分钟到半小时。

## 6. 验证清单（从免费到花钱，按顺序）

| # | 验什么 | 怎么验 | 规格出处 |
|---|---|---|---|
| 1 | 站开得起来、不被收录 | `curl -I https://listen-app.bayescode.com` → 200 且有 `X-Robots-Tag: noindex` | A64 |
| 2 | 锁标正常 | 浏览器地址栏 HTTPS 锁标 | A68 |
| 3 | 注册要邀请码、错码进不来 | 浏览器走一遍注册 | A72 |
| 4 | 新账号空库待机、上传不自动备课 | 传一集 mp3，资料库里是带「备课」按钮的材料 | A73、A75 |
| 5 | **真材料备课六步（花钱，先跟 owner 说）** | 传 BBC 一集 mp3＋页面讲稿纯文本，点「备课」，几分钟后变课、能播、点词能查 | A76、A70 |
| 6 | 两个账号互相看不见 | 注册第二个账号，看不到第一个的课 | A73 |
| 7 | 学习记录刷新还在 | 听几句刷新，进度点还是半满 | A71 |
| 8 | 带宽 | 同时开几个标签听；卡到受不了记下来（顶约 15 路，R9 迁移触发） | 观察 |

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
- **备份**：`server-data/` 是各家自己上传的资料库，丢了无法重建。定期 `tar -czf server-data-$(date +%F).tar.gz server-data/` 拉回开发机一份。
- **找回密码**：没有自助（SPEC-009 不做），家长找 owner、owner 转给 claude：在服务器上用 `pipeline/accounts.py` 的存法给该邮箱重写一条密码哈希（PBKDF2，照 `register` 的写法生成），顺手清掉它的旧会话。
- **下线/回滚**：`systemctl stop listening` 即下线；要连域名一起撤，把 Caddy 里那三行删掉 reload。代码回滚用留底的 `Caddyfile.server-backup` 和上一版 archive。

## 8. 迁移（不急，写在这备忘）

并发经常接近 15 路、或家长超过约 20 家 → 迁 ECS，照 `docs/refs/阿里云配置指南.md` §4 的从零搭机手册；这台轻量上的东西整体搬（代码、词典、server-data、Caddy 块）。
