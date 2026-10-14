# 四川麻将训练

一个人练成都血战到底。你坐东家，另外三家是服务端人机。浏览器只负责出牌，胡牌、番数和谁付钱都由服务端判定。没有匹配，也没有多人对战。

每人开局 **100 分**。任意一家到 **0 分或以下**，这一整局结束。再开一局，四家都恢复为 100 分。和牌账本仍然是零和，所以结束时分数可以是负数，下一局不会把这个负数带过去。

可以注册登录。每一步会自动保存，刷新页面可以继续。牌桌上也可以起名保存，下次在大厅加载。加载会新开一局，已经走过的人机决定不会重算。

规则版本是 `chengdu-xz-1`：108 张牌，不能吃，默认换三张，定缺，血战到三家胡或牌墙摸完。封顶 5 番。细则在游戏里的「规则」页，也在 `docs/sichuan-mahjong-trainer-design.md`。

## 用到的端口

| 场合 | 端口 | 说明 |
| --- | --- | --- |
| 腾讯云对外 | **23333** | 默认。不占用 80。安全组放行这一条 |
| 本机网页开发 | 5173 | 只在你自己的电脑上 |
| 本机接口 | 8000 | 只在你自己的电脑上，由网页开发服务器转发 |
| 容器内部的接口 | 8000 | 不映射到宿主机 |
| Postgres | 5432 | 只在 Compose 网络里，不映射到宿主机 |

要改对外端口，在 `deploy/.env` 里设置 `HTTP_PORT`，然后重新 `up -d`。

## 本机直接玩

需要 Python 3.12 或更高版本，以及 Node.js 20 左右。不需要 Docker。

在仓库根目录：

```bash
python3 -m venv .venv
.venv/bin/pip install -r apps/api/requirements.txt
```

国内安装依赖如果卡住，改用清华源：

```bash
.venv/bin/pip install -r apps/api/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

启动接口：

```bash
cd apps/api
../.venv/bin/uvicorn cmahjong.http:app --reload --port 8000
```

另一个终端启动网页。国内 `npm install` 慢或超时时，先换源：

```bash
cd apps/web
npm config set registry https://registry.npmmirror.com
npm install
npm run dev
```

打开 http://localhost:5173 ，注册后开始。账号存在 SQLite 文件 `apps/api/cmahjong.db`。删掉这个文件等于清空本机账号和对局。

## 部署到腾讯云

一台轻量应用服务器或云服务器即可，2 核 4 GB 足够。系统用 Ubuntu 22.04 或 24.04。下面的命令在仓库根目录执行。

### 1. 安装 Docker

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
```

执行完后重新登录，让 `docker` 组生效。然后确认：

```bash
docker version
docker compose version
```

### 2. 拉取代码

```bash
git clone https://github.com/solitern/CMahjong.git
cd CMahjong
cp deploy/.env.example deploy/.env
```

编辑 `deploy/.env`，至少把 `POSTGRES_PASSWORD` 换成一串自己的密码。`deploy/.env.example` 里已经把 pip 和 npm 指到国内源。Compose 会自动读取 `deploy/.env`。

`git clone` 如果连不上 GitHub，可以在能访问的电脑上把仓库打成 zip，用 `scp` 传到服务器再解压。解压后的目录里要能看到 `deploy/docker-compose.yml`。

### 3. 国内服务器先解决镜像拉取

`docker compose up --build` 会拉取这 4 个镜像：

| 镜像 | 用途 |
| --- | --- |
| `postgres:16` | 数据库，写在 Compose 里 |
| `python:3.12-slim` | 构建接口 |
| `node:20-alpine` | 构建网页 |
| `nginx:1.27-alpine` | 对外提供网页并转发接口 |

它们都在 Docker Hub。国内机器直接拉，常见报错是 `TLS handshake timeout`、`i/o timeout`、`dial tcp ... registry-1.docker.io:443`、`Context deadline exceeded`。这是访问 Docker Hub 失败，不是项目本身的错误。

腾讯云上的云服务器、轻量服务器，优先用腾讯云镜像加速。这个地址只在腾讯云内网有效，家里的电脑配了也拉不动。

```bash
sudo mkdir -p /etc/docker
sudo tee /etc/docker/daemon.json >/dev/null <<'EOF'
{
  "registry-mirrors": ["https://mirror.ccs.tencentyun.com"]
}
EOF
sudo systemctl daemon-reload
sudo systemctl restart docker
docker info | sed -n '/Registry Mirrors/,+3p'
```

`Registry Mirrors` 下面应能看到 `https://mirror.ccs.tencentyun.com`。然后再构建。Docker 仍然使用原来的镜像名，加速由守护进程完成，不用改 Compose。

不在腾讯云上、或者上面的地址超时，再换一个公开加速器。公开加速器经常失效，失败就换下一个，不要在一个地址上反复重试。

阿里云需要登录容器镜像服务，打开「镜像工具 / 镜像加速器」，复制你自己的专属地址，形如 `https://xxxx.mirror.aliyuncs.com`，写进上面的 `registry-mirrors`，然后同样 `systemctl restart docker`。

也可以不改守护进程，手动拉下来再打回 Compose 认识的名字。下面以 DaoCloud 为例，`library/` 不能省，官方镜像在 Docker Hub 上属于 `library`：

```bash
MIRROR=docker.m.daocloud.io
for image in postgres:16 python:3.12-slim node:20-alpine nginx:1.27-alpine; do
  docker pull "$MIRROR/library/$image"
  docker tag "$MIRROR/library/$image" "$image"
done
docker images
```

四个名字都能在 `docker images` 里看到之后，Compose 会用本地镜像，不会再去 Docker Hub。某个镜像 `not found` 时，试试去掉 `library/`，例如 `docker.m.daocloud.io/nginx:1.27-alpine`。

`systemctl restart docker` 会短暂停下这台机器上已有的容器。第一次部署时机器上通常还没有这个项目的容器，可以直接重启。

### 4. 构建时的 pip 和 npm

镜像拉下来之后，构建还要安装 Python 包和前端依赖。国内访问 `pypi.org` 和 `registry.npmjs.org` 也会超时。`deploy/.env.example` 已默认：

```text
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
NPM_REGISTRY=https://registry.npmmirror.com
```

这只影响**构建容器**，不改变你本机的 pip 或 npm。清华源不可用时，把 `PIP_INDEX_URL` 换成 `https://mirrors.aliyun.com/pypi/simple/`。npmmirror 不可用时，前端可以改回 `https://registry.npmjs.org`，在能访问外网的机器上构建好再把镜像导出。

改了 `.env` 里的源之后要重新构建，不能只用 `up -d`：

```bash
docker compose -f deploy/docker-compose.yml build --no-cache
```

### 5. 启动

```bash
docker compose -f deploy/docker-compose.yml up -d --build
docker compose -f deploy/docker-compose.yml ps
```

三个容器名应是 `cmahjong-postgres`、`cmahjong-api`、`cmahjong-nginx`，状态为 running。

腾讯云控制台的安全组入站放行 **TCP 23333**。来源可以先写成你自己的公网 IP。安全组和系统防火墙是两道门：安全组放行了，如果系统里还有 `ufw` 或 `firewalld`，也要放行 23333。

```bash
sudo ufw allow 23333/tcp
```

没有启用 ufw 就不用执行。然后在浏览器打开：

```text
http://服务器公网IP:23333
```

页面和接口都从 23333 进来，一般不用改 `WEB_ORIGIN`。只有网页单独放在另一个域名时才改它，并写成带端口的完整地址，例如 `http://1.2.3.4:23333`。

第一次打开先注册。注册成功后会自动登录。`ALLOW_REGISTER=false` 会关掉网页注册，避免安全组放得太宽时别人来建号。关掉之前先自己注册一个账号。

默认是 HTTP，`COOKIE_SECURE` 保持 `false`。如果以后前面加了 HTTPS，再把它改成 `true` 并重建 api 容器。在 HTTP 上把它设成 `true`，登录会看起来成功，下一跳就掉回登录页。

### 6. 更新、日志、备份

服务器上更新：

```bash
git pull
docker compose -f deploy/docker-compose.yml up -d --build
```

看日志：

```bash
docker compose -f deploy/docker-compose.yml logs -f --tail 100 api
docker compose -f deploy/docker-compose.yml logs -f --tail 100 nginx
```

数据库在命名卷 `pgdata` 里。`docker compose down` 不会删卷。`docker compose down -v` 会删掉全部账号和对局，不要随手加 `-v`。

备份：

```bash
docker exec cmahjong-postgres pg_dump -U cmahjong cmahjong > "cmahjong-$(date +%F).sql"
```

恢复到一台空库：

```bash
docker exec -i cmahjong-postgres psql -U cmahjong cmahjong < cmahjong-2026-01-01.sql
```

## 构建失败时先看哪一句

- 报错里有 `registry-1.docker.io`、`docker.io`、`TLS handshake timeout`：还是镜像没拉下来。回到第 3 节，先 `docker pull postgres:16` 单独试。这个命令成功，另外三个再逐个试。
- 镜像已经在 `docker images` 里，报错出现在 `pip install`：改 `PIP_INDEX_URL`，然后 `docker compose -f deploy/docker-compose.yml build --no-cache api`。
- 报错出现在 `npm install` 或 `npm run build`：改 `NPM_REGISTRY`，然后 `docker compose -f deploy/docker-compose.yml build --no-cache nginx`。
- 容器都是 running，浏览器打不开：看安全组是不是 23333，以及 `docker compose ps` 里 nginx 的端口映射是不是 `0.0.0.0:23333->23333`。
- 能打开页面，注册或登录显示「请求失败」或「接口没有起来」：网页已经在，接口或数据库没有。先看 `docker compose -f deploy/docker-compose.yml ps`，`cmahjong-api` 应是 running。再看 `docker compose -f deploy/docker-compose.yml logs --tail 80 api`。
- 日志里是密码认证失败：数据卷是用第一次的 `POSTGRES_PASSWORD` 初始化的。之后只改 `.env` 不会改掉库里的密码。把 `.env` 改回第一次的密码，或者确认可以清空对局后执行 `docker compose -f deploy/docker-compose.yml down -v` 再重新 `up -d --build`。
- 更新到这次修复后要重建网页和接口，否则浏览器里还是旧页面：`docker compose -f deploy/docker-compose.yml up -d --build`。
