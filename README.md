# Sciencia Data Ingestion System

这是一个面向 Phase I「Data Ingestion & Infrastructure」的基础项目。它把公开网页数据采集、清洗结构化、关系型数据库存储和基础健康检查拆成独立模块，方便后续替换数据源、接入标注系统或训练 pipeline。

## 项目结构

```text
code/
├── main.py
├── config.py
├── requirements.txt
├── .env
├── acquisition/
│   ├── fetch_reviews.py
│   ├── pagination.py
│   ├── headers.py
│   └── html_parser.py
├── structuring/
│   ├── parser.py
│   ├── cleaner.py
│   ├── validator.py
│   └── transformer.py
├── storage/
│   ├── models.py
│   ├── database.py
│   ├── insert.py
│   └── queries.py
├── logs/
└── data/
    ├── raw/
    └── processed/
```

## 功能说明

### 1. 数据采集 `acquisition/`

- `headers.py` 统一生成请求头，包括 `User-Agent`，便于遵守目标站点的访问规则。
- `pagination.py` 解析分页中的 `next` 链接，让采集过程可以自动翻页。
- `html_parser.py` 优先使用 `lxml`，环境里没有可用 parser 时自动退回 `html.parser`。
- `fetch_reviews.py` 提供两个数据源：
  - `books`：默认真实网页来源，抓取 `books.toscrape.com` 的商品列表和详情页，将商品评分、描述、价格、库存等信息整理为 review-like 文本记录。
  - `sample`：离线样例数据，不需要网络，适合演示、测试数据库和清洗逻辑。

### 2. 数据结构化 `structuring/`

- `cleaner.py` 负责文本去 HTML 转义、空白字符规范化、评分转换、日期转 UTC。
- `parser.py` 将原始字典转换成 `CleanReview` 数据类。
- `validator.py` 校验必填字段、评分范围等规则。
- `transformer.py` 串起 parse + validate，并过滤批内重复记录。

### 3. 数据存储 `storage/`

- `models.py` 使用 SQLAlchemy 定义两张表：
  - `products`：产品维度信息。
  - `reviews`：评论/评分维度信息，包含来源唯一键、文本、评分、时间、原始 payload。
- `database.py` 初始化数据库连接，默认使用 SQLite：`data/reviews.db`。
- `insert.py` 实现 upsert：同一个 `source + source_review_id` 重复运行时会更新，不会重复插入。
- `queries.py` 提供基础健康检查：产品数、评论数、平均评分、来源分布、最新记录。

## 安装

推荐使用现有虚拟环境：

```powershell
SCI\Scripts\python.exe -m pip install -r requirements.txt
```

也可以新建环境后安装：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 配置

`.env` 中可以调整运行参数：

```dotenv
SOURCE=books
BASE_URL=https://books.toscrape.com/
MAX_PAGES=3
REQUEST_TIMEOUT=15
REQUEST_DELAY_SECONDS=1.0
DATABASE_URL=sqlite:///data/reviews.db
```

如果只是想离线验证流程，把 `SOURCE=sample`，或运行命令时传 `--source sample`。

## 使用方式

运行离线样例：

```powershell
SCI\Scripts\python.exe main.py --source sample
```

运行真实网页采集，限制抓取 2 页：

```powershell
SCI\Scripts\python.exe main.py --source books --max-pages 2
```

只查看数据库摘要，不重新采集：

```powershell
SCI\Scripts\python.exe main.py --summary-only
```

不保存 raw JSON 和 processed CSV，只写数据库：

```powershell
SCI\Scripts\python.exe main.py --source sample --no-files
```

## 输出文件

- `data/raw/reviews_raw_*.json`：原始采集快照，便于追溯和 debug。
- `data/processed/reviews_clean_*.csv`：清洗后的结构化数据。
- `data/reviews.db`：SQLite 数据库。
- `logs/ingestion.log`：运行日志。

## 后续扩展建议

- 新增数据源时，在 `fetch_reviews.py` 中添加新的 fetcher，并在 `main.py` 的 `choices` 中加入来源名。
- 生产部署时可以把 `DATABASE_URL` 改成 PostgreSQL，例如 `postgresql+psycopg://user:pass@host:5432/dbname`。
- 下游建模可以直接读取 `reviews.text`、`reviews.rating`、`products.name`，也可以从 `data/processed/*.csv` 启动实验。
