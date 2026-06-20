# AllDocs

面向操作指南、维修手册等文档的 **RAG 问答系统**：上传手册后，通过混合检索与 Agent 多步取证回答用户问题，支持引用来源、插图展示与语音交互。

---

## 功能概览

- 多格式文档上传与异步索引（PDF、Word、Markdown、图片等）
- PDF 书签章节、矢量表格与内嵌插图解析
- 混合检索：Qdrant 向量 + Elasticsearch 全文（RRF 融合）+ Cross-encoder rerank
- Retrieval Agent：`list_outline`、`lookup_toc`、`search_chunks`、`read_chunks` 等工具多步检索
- 流式对话、引用跳转、可选入库 VLM caption 与 `{{embed:N}}` 句级插图对齐
- WebSocket 语音问答（Whisper 转写 + Piper 合成）

---

## 架构

```mermaid
flowchart LR
    subgraph client [Frontend]
        UI[Vite + React]
    end
    subgraph api [API]
        FastAPI[FastAPI]
        Agent[Retrieval Agent]
        LLM[LLM API]
    end
    subgraph worker [Worker]
        Celery[Celery]
        Ingest[IngestionService]
    end
    subgraph stores [Storage]
        PG[(PostgreSQL)]
        MinIO[(MinIO)]
        Qdrant[(Qdrant)]
        ES[(Elasticsearch)]
        Redis[(Redis)]
    end
    subgraph optional [Optional]
        Inference[Inference Service]
    end
    UI --> FastAPI
    FastAPI --> Agent
    FastAPI --> PG
    Agent --> Qdrant
    Agent --> ES
    Agent --> LLM
    FastAPI --> Redis
    Redis --> Celery
    Celery --> Ingest
    Ingest --> PG
    Ingest --> MinIO
    Ingest --> Qdrant
    Ingest --> ES
    Agent -.-> Inference
    Ingest -.-> Inference
```

| 组件 | 作用 |
|------|------|
| **PostgreSQL** | 文档、chunk、asset、会话与消息 |
| **MinIO** | 原始文件与表格/插图 PNG |
| **Qdrant** | chunk 向量（语义检索） |
| **Elasticsearch** | 正文与 caption 全文索引（IK 分词） |
| **Redis** | Celery 消息队列 |
| **Celery Worker** | 文档解析、向量化、索引写入 |
| **Inference**（可选） | 独立 HTTP 服务承载 BGE embed / rerank，减轻 api/worker 内存 |

前后端共享契约位于 `backend/shared/`（`file_formats.json`、`markers.json`），由 Python `shared_contract.py` 与前端 `@shared` 别名共同引用。

---

## 快速开始

### 环境要求

- Docker Desktop（含 `docker compose`）
- Node.js 18+（仅开发模式本地前端）
- 可访问的 LLM API（在 `.env` 中配置 `LLM_API_KEY`）

### 开发模式

```bash
cp .env.example .env   # 编辑 LLM_API_KEY 等
./dev.sh               # Docker 后端 + 本地 Vite 前端
```

| 地址 | 说明 |
|------|------|
| http://localhost:3000 | 前端（Vite，`vite.config.ts` 固定端口） |
| http://localhost:8000 | API |
| http://localhost:8000/docs | OpenAPI 文档 |
| http://localhost:9001 | MinIO Console |

常用命令：

```bash
./dev.sh --build       # 重新构建镜像
./dev.sh --docker      # 生产 Compose（Nginx 前端，端口 3000）
./dev.sh --stop        # 停止所有 Docker 服务
docker compose logs -f api worker
```

可选：启用独立推理服务 offload embedding/rerank：

```bash
docker compose --profile inference up -d inference
# .env 中设置 INFERENCE_URL=http://inference:8100
```

首次启动会自动：从 `.env.example` 生成 `.env`、检查并下载 Embedding/Rerank 模型与 Piper 语音模型。

环境变量：`SKIP_PIPER=1`（跳过语音模型）、`SKIP_NPM_INSTALL=1`（跳过 `npm install`）、`USE_DOCKER_MIRROR=1`（镜像站拉取基础镜像）。

---

## 项目结构

```
AllDocs/
├── backend/
│   ├── app/
│   │   ├── api/              # documents, chat, assets, ws_voice
│   │   ├── services/         # ingestion, rag, llm, vector_store, …
│   │   │   └── agent/        # Retrieval Agent、answer_flow、工具注册
│   │   ├── inference/        # 可选 BGE embed/rerank HTTP 服务
│   │   └── workers/          # Celery 任务
│   ├── shared/               # 前后端共享契约（格式、标记正则）
│   └── tests/
├── frontend/                 # Vite + React 前端
├── docker/                   # Elasticsearch 等镜像构建
├── docs/
│   └── manual-writing-guide.md   # 操作手册编写规范（面向文档作者）
├── scripts/                  # 模型下载、部署脚本
├── dev.sh                    # 一键开发启动
├── docker-compose.yml
└── .env.example
```

---

## 文档入库流程

上传后由 Celery Worker 异步执行：

**解析 → 切 chunk → 上传 asset →（可选）VLM caption → 向量化 → 混合索引 → 入库**

```mermaid
flowchart TD
    A[上传文档] --> B[Celery Worker]
    B --> C{文件类型}
    C -->|PDF| D[读取书签 + 页面文本]
    C -->|DOCX/MD| E[按标题切 section]
    C -->|图片| F[整图 OCR]
    D --> G[提取矢量表格 + 内嵌位图]
    D --> H[整页文本 + 可选 OCR]
    G --> I[剔除 asset 区域后按 section 合并]
    H --> I
    E --> I
    F --> I
    I --> J["固定长度切分 (默认 500 字, 重叠 80 字)"]
    J --> K[挂靠/孤儿 asset 合并 + 句级 sub_index]
    K --> L[PostgreSQL + MinIO]
    L --> M{INGEST_CAPTION_ENABLED?}
    M -->|是| N[VLM 为插图/表格生成 caption]
    M -->|否| O[跳过]
    N --> P[Qdrant + Elasticsearch]
    O --> P
```

### 支持格式

| 格式 | section 来源 |
|------|--------------|
| **PDF** | 书签（Bookmark / 大纲） |
| **DOCX** | Heading 1–6 段落样式 |
| **Markdown** | `#` 标题行 |
| **TXT / HTML** | 无 section |
| **PNG / JPG / WEBP** | 无 section；整图 OCR |

### Chunk 字段

| 字段 | 含义 |
|------|------|
| `text` | 正文（表格/插图区域内文字已剔除） |
| `page` | 页码（1 起） |
| `section` | 章节路径，如 `第一章 > 1.2 安装` |
| `chunk_index` | 文档内阅读顺序 |
| `caption` | chunk 级图像描述（可选，独立字段） |
| `layout_bbox` / `layout_regions` | 版面坐标，供文档查看器高亮 |
| `sub_index` | 句级子索引，关联句子与 asset（图号引用配对） |
| `assets` | 关联表格/插图（`ChunkAsset`，PNG 存 MinIO） |

`caption` 与 `assets[].caption` / `assets[].vlm_caption` 不写入 `chunk.text`；向量化时通过 `chunk_embedding_text` 以 `[visual] …` 拼接到索引文本。

默认切分：`RAG_CHUNK_SIZE=500`、`RAG_CHUNK_OVERLAP=80`（见 `.env`）。

### PDF 处理要点

- **书签**：生成 `section` 与 `toc_entries`；同页多书签时依赖页内 **Y 坐标**切分（非 OCR 页）。书签目标应指向页内具体段落，避免仅绑定页码（见 [手册编写规范 · PDF 书签](docs/manual-writing-guide.md#4-pdf-书签)）
- **矢量表格**：`find_tables()` 整表提取为 `table` asset，摘要写入 `assets.caption`
- **内嵌位图**：提取为 `figure` asset；扫描整页图通常因面积过大被跳过
- **前置页**：自动跳过「第一章」之前的封面/版权等（可调整书签规避）
- **目录页**：带点线引导符的目录样式页自动忽略
- **页眉页脚**：裁切上下边距区域，并剔除跨页重复的页眉页脚文本与页码（见 [手册编写规范](docs/manual-writing-guide.md)）

实现参考：`backend/app/services/ingestion.py`、`pdf_header_footer.py`、`pdf_tables.py`、`pdf_embedded_images.py`、`chunk_alignment.py`、`workers/tasks.py`。

---

## 问答检索

用户提问时，**Retrieval Agent** 多步调用工具收集证据，再流式合成回答。

### Agent 工具

| 工具 | 用途 |
|------|------|
| `list_outline` | 列出文档章节树 |
| `lookup_toc` | 查询章节起止页码 |
| `search_chunks` / `search_chunks_batch` | 混合检索；支持 `asset_types`、`section_prefix`、`page_gte` 等过滤 |
| `read_chunks` / `read_neighbor_chunks` | 精读 chunk 及相邻上下文 |
| `ask_user` | 信息不足时向用户澄清（仅问一点） |
| `finish` | 结束检索进入合成 |

检索链路：**Qdrant + Elasticsearch（RRF）→ rerank → Agent 选取证据 → LLM 合成**。

Agent 限制（`.env`）：`RAG_AGENT_MAX_STEPS=10`、`RAG_AGENT_MAX_RETRIEVALS=6`、`RAG_BATCH_SEARCH_MAX=3`。

### 回答合成

`answer_flow.py` 统一 chat SSE 与语音 WebSocket 的流水线：

1. Agent 收集 `evidence[]`（或 `ask_user` 澄清 / 无证据 fallback）
2. `build_context()` 格式化为 `<context>` 注入 LLM
3. `chat_stream()` 流式生成带 `[n]` 引用的回答
4. `finalize_answer_async()`：重排引用序号、句级对齐 `{{embed:N}}` 插图（`answer_alignment.py`）
5. 前端渲染 Markdown、点击 `[n]` 跳转文档查看器并高亮 `layout_regions`

### Chat SSE 事件

`POST /api/v1/chat` 返回 `text/event-stream`，主要事件类型：

| 类型 | 说明 |
|------|------|
| `status` | 阶段提示（如 `agent`） |
| `agent_step_start` / `agent_thought_delta` / `agent_step` | Agent 推理步骤（前端展示检索过程） |
| `citations` | 证据来源列表（合成前） |
| `delta` | 回答文本增量 |
| `embeds` | 句级对齐后的插图/表格元数据 |
| `done` | 完成（含 `session_id`、`content`、`citations`、`embeds`） |
| `error` | 异常信息 |

语音通道 `WebSocket /ws/voice` 复用同一 Agent 流水线，回答经 Piper TTS 按句输出。

---

## API 概览

前缀 `/api/v1`（WebSocket 除外）：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/documents` | 上传（同名文件触发重新索引） |
| GET | `/documents` | 文档列表 |
| GET | `/documents/formats` | 支持格式 |
| GET | `/documents/{id}/file` | 下载原文件 |
| GET | `/documents/{id}/pages/{page}/render` | 页面 PNG |
| POST | `/documents/{id}/reindex` | 重新入库 |
| DELETE | `/documents/{id}` | 异步删除 |
| POST | `/chat` | SSE 流式问答 |
| GET | `/assets/{asset_id}` | 表格/插图 PNG |
| WS | `/ws/voice` | 语音问答 |
| GET | `/health` | 健康检查 |

文档状态：`pending` → `processing` → `ready` | `failed` | `deleting`。

---

## 配置说明

复制 `.env.example` 为 `.env`，主要配置组：

| 配置组 | 关键变量 |
|--------|----------|
| LLM | `LLM_API_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` |
| 入库 Caption | `INGEST_CAPTION_ENABLED`、`INGEST_CAPTION_*`（入库 VLM 描述，可选） |
| Embedding / Rerank | `EMBEDDING_MODEL`、`RERANK_MODEL`、`RERANK_ENABLED` |
| 远程推理 | `INFERENCE_URL`（可选，见 `docker compose --profile inference`） |
| RAG / Agent | `RAG_CHUNK_SIZE`、`RAG_RETRIEVE_K`、`RAG_TOP_K`、`RAG_AGENT_*`、`HYBRID_ENABLED` |
| OCR / PDF | `OCR_*`、`PDF_EXTRACT_TABLES`、`PDF_EXTRACT_EMBEDDED_IMAGES`、`PDF_FILTER_HEADER_FOOTER`、`PDF_*_MARGIN_RATIO` |
| 基础设施 | `POSTGRES_URL`、`QDRANT_URL`、`ELASTICSEARCH_URL`、`MINIO_*` |

完整列表见 [`.env.example`](.env.example)。

---

## 操作手册编写

上传文档的质量直接影响检索与问答效果。面向文档编写人员的规范见：

**[docs/manual-writing-guide.md](docs/manual-writing-guide.md)**

涵盖：图注与图号引用、PDF 书签、内容与排版要点及上传前检查清单。
