# InkMill-01 · 油墨研磨台账

面向印刷油墨研磨车间的**研磨机状态、粘度取样与研磨遍次**台账系统。  
**不是**库存、电商或 CMS 场景。

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.11、Flask、SQLAlchemy、PyMySQL、Flask-JWT-Extended、passlib/bcrypt、gunicorn |
| 前端 | Svelte 4、Vite、TypeScript |
| 数据库 | MySQL 8 |

## 端口与数据库

| 服务 | 宿主机端口 |
|------|------------|
| 统一入口 (Nginx) | **4200** |
| 后端 API | **9200** |
| MySQL | **3312** |

MySQL 连接：`inkmill` / `inkmill` / `inkmill`（库名/用户/密码）

## 演示账号

密码均为 **123456**：

- `admin` — 管理员
- `grinder` — 研磨工

## 领域实体（JSON 驼峰）

1. **Workshop**：`name`, `site`, `notes`
2. **Mill**：`workshopId`, `millCode`（同车间唯一）, `pigmentBase`, `bowlLiters`, `status`（`grinding` \| `idle` \| `wash`）, `hasOpenPass`（是否有进行中遍次，接口给出）
3. **ViscositySample**：`millId`, `sampledAt`, `viscosityPaS`（须 &gt; 0，否则 HTTP 400）, `tempC`, `notes`
4. **GrindPass**：`millId`, `startedAt`, `endedAt`（可空，空 = 进行中）, `open`（是否进行中，接口给出）, `passNo`（≥ 1）, `durationMin`（分钟，结束时由服务端计算）, `mediaType`, `operatorName`
5. **Dashboard**：`workshopTotal`, `grindingMillCount`, `samplesLast24h`, `passesLast7d`

## 研磨遍次生命周期

遍次分**进行中**（`endedAt` 为空，`open=true`）与**已结束**两种状态，规则均由服务端强制：

- **新建**（`POST /api/grind-passes`）：即创建一条进行中遍次。研磨机 `status` 必须为 `grinding`，否则 409；同一研磨机同时最多一条进行中遍次，已有进行中时再建返回 409；进行中创建时 `durationMin` 允许为 0。
- **结束**（`POST /api/grind-passes/<id>/end`）：`endedAt` 必须晚于 `startedAt`（缺省取服务器当前时间）。服务端按起止时间之差计算 `durationMin`（分钟，必须 &gt; 0）并落库，**不采用客户端上报的时长**；若请求另带 `durationMin` 且与计算值相差超过 1 分钟，返回 400 且不写入。已结束的遍次重复结束返回 409。
- **修改**（`PUT /api/grind-passes/<id>`）：仅进行中遍次可改，已结束返回 409。
- **删除**（`DELETE /api/grind-passes/<id>`）：已结束遍次禁止删除，返回 409；进行中可删。
- **列表**：每行带 `open` 与 `endedAt`；研磨机列表带 `hasOpenPass`，均由服务端给出，前端不自行统计。

种子数据中 M-01 有一条进行中遍次（另有若干已结束），M-02 只有已结束遍次。

## 快速启动（Docker）

```bash
cd InkMill-01
docker compose up --build -d
```

浏览器访问：**http://localhost:4200**  
前端 Nginx 将 `/api/` 反向代理到后端 `9200`。

后端容器启动流程：

1. 等待 MySQL 就绪（`DB_HOST=mysql`）
2. SQLAlchemy `create_all` 建表
3. `SEED_ON_START=true` 时写入演示数据
4. gunicorn 监听 `0.0.0.0:9200`

健康检查：`GET /api/health` → `{"status":"ok","service":"InkMill"}`

## 本地开发（可选）

**后端**（需本机 MySQL 或连 Docker 的 3312 端口）：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
set DB_HOST=127.0.0.1
set DB_PORT=3312
set DB_USER=inkmill
set DB_PASSWORD=inkmill
set DB_NAME=inkmill
set JWT_SECRET=inkmill-jwt-secret-change-me
python -c "from app.database import Base, engine; from app import models; Base.metadata.create_all(bind=engine)"
python -c "from app.seed import seed; seed()"
gunicorn wsgi:app --bind 127.0.0.1:9200 --reload
```

**前端**：

```bash
cd frontend
npm install
npm run dev
```

Vite 开发服务器端口 **4200**，`/api` 代理到 `127.0.0.1:9200`。

## 目录结构

```
InkMill-01/
├── docker-compose.yml
├── nginx/nginx.conf          # 4200 统一入口，/api → backend
├── backend/
│   ├── Dockerfile
│   ├── entrypoint.sh
│   ├── requirements.txt
│   ├── wsgi.py
│   └── app/                  # Flask 路由、模型与种子数据
└── frontend/
    ├── Dockerfile
    ├── vite.config.ts
    └── src/routes/           # Login / Dashboard / CRUD 页面
```

## UI 主题

墨黑底 + 朱砂强调色，无紫色光晕风格。
