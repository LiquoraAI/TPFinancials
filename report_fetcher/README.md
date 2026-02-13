# 定期报告抓取：AKShare → 巨潮 cninfo → 下载 PDF

自动抓取指定 A 股公司的**定期报告**（年报/半年报/一季报/三季报），将 PDF 下载到本地 `reports/`，并生成 `index.csv` 元数据索引，支持**增量更新**（已下载的不重复拉取）。

## 公司清单（默认）

| 名称     | 代码   |
|----------|--------|
| 若羽臣   | 003010 |
| 丽人丽妆 | 605136 |
| 壹网壹创 | 300792 |
| 青木科技 | 301110 |
| 凯淳股份 | 301001 |

## 环境

- Python 3.8+
- 依赖见 `requirements.txt`

```bash
cd report_fetcher
pip install -r requirements.txt
```

## 使用

```bash
# 默认：近 5 年、4 类报告、5 家公司，输出到 ./reports
python main.py

# 只拉近 2 年
python main.py --years 2

# 指定输出目录
python main.py --out my_reports

# 只拉指定公司（逗号分隔）
python main.py --codes 003010,605136

# 只拉年报、半年报
python main.py --categories 年报,半年报
```

## 项目结构（运行后）

```
report_fetcher/
  main.py
  config.py
  requirements.txt
  README.md
  reports/              # 输出目录
    003010_若羽臣/
    605136_丽人丽妆/
    ...
  state/
    downloaded.json     # 已下载去重记录
  index.csv             # 全量元数据索引
  failed.csv            # 解析/下载失败记录（若有）
```

## 索引字段说明

`index.csv` 列：`stock_code`, `stock_name`, `category`, `publish_date`, `title`, `pdf_url`, `local_path`, `fetched_at`。

## 数据维护 API（与看板「数据维护」Tab 配合）

看板中有一个 **数据维护** Tab，可人工点击「Update最新数据」触发拉取，并查看各公司获取成功与否的表格日志。

1. 在 `report_fetcher` 目录下启动 API 服务：
   ```bash
   pip install flask flask-cors
   python server.py
   ```
   默认运行在 `http://127.0.0.1:5000`。

2. 看板前端会请求：
   - `GET /api/log`：获取最近一次更新的日志（表格数据）
   - `POST /api/update-reports`：执行一次更新，返回本次各公司状态并写入 `state/last_run_log.json`

3. 若看板与 API 不同机或不同端口，需在浏览器侧配置 API 地址（当前前端写死为 `http://127.0.0.1:5000`，可在 `js/app.js` 中修改 `DATA_MAINT_API_BASE`）。

## 注意事项

- **AKShare 接口**：当前按 `stock_zh_a_disclosure_report_cninfo` 调用；若你使用的 akshare 版本中函数名或参数有变，请查看 [AKShare 文档](https://akshare.akfamily.xyz/) 并相应修改 `main.py` 中 `fetch_report_list_akshare`。
- **限速**：每次请求后随机 sleep 0.5～1.5 秒，下载失败会重试 3 次（指数退避）。
- **失败记录**：无法解析 PDF 链接或下载失败的条目会写入 `failed.csv`，便于排查。
