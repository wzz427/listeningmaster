# 听力站·应用镜像（182.92.206.53，服务器部署指南 §6.1 第 5 步的后端形态）：
# serve.py 对外模式＋备课六步全在容器里跑，没有单独的静态容器——整站都要过会话门，
# 音频还带账号指路，拆静态层会绕过权限。
# 构建（在服务器 /opt/listening 下，代码由 git archive 铺好）：
#   docker build -f deploy/Dockerfile -t listening-app:<git短sha> .
# 密钥、配置、账号数据、备课台、发音词典都不进镜像（.dockerignore 挡＋运行时挂载）。
FROM python:3.12-slim

WORKDIR /opt/listening

# 依赖单独一层：代码天天换、依赖不常换，这层能一直命中缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ -r requirements.txt

COPY . .

EXPOSE 8790
# 对外模式；bind 在挂进去的 server-config.json 里写 0.0.0.0（容器网络里只有网关够得着它）
CMD ["python", "pipeline/serve.py", "--hosted"]
