# 四川麻将训练

一个人练成都血战到底。你坐东家，另外三家是服务端人机。浏览器只负责出牌，胡牌、番数和谁付钱都由服务端判定。

每人开局 **100 分**。任意一家到 **0 分或以下**，这一整局结束。再开一局，四家都恢复为 100 分。

## 本机直接玩

```bash
cd apps/api
python3 -m venv .venv
. .venv/bin/pip install -r requirements.txt   # 若 venv 已在仓库根的 .venv，用那个解释器
```

仓库根目录如果已经有 `.venv`：

```bash
.venv/bin/pip install -r apps/api/requirements.txt
cd apps/api && ../.venv/bin/uvicorn cmahjong.http:app --reload --port 8000
```

另一个终端：

```bash
cd apps/web
npm install
npm run dev
```

打开 http://localhost:5173 ，注册后开始。默认使用 SQLite 文件 `apps/api/cmahjong.db`。

## 腾讯云

`deploy/docker-compose.yml` 跑 nginx、API 和 PostgreSQL。把 `.env.example` 抄成 `.env` 后：

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

安全组开放 80 和 443。验收走 HTTPS。`COOKIE_SECURE=true` 时浏览器必须用 https 打开，否则登录态存不住。

## 规则

锁定 `chengdu-xz-1`。说明见 `docs/sichuan-mahjong-trainer-design.md` 和游戏里的规则页。
