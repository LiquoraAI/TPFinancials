# -*- coding: utf-8 -*-
"""
用 AKShare 抓取 5 家公司定期报告（巨潮 cninfo），下载 PDF 到 ./reports，生成 index.csv，支持增量更新。
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    pd = None
try:
    import requests
except ImportError:
    requests = None

from config import (
    BACKOFF_BASE,
    COLUMN_ALIASES,
    DEFAULT_CATEGORIES,
    DEFAULT_OUT_DIR,
    DEFAULT_YEARS,
    DOWNLOAD_RETRIES,
    DOWNLOAD_TIMEOUT,
    FAILED_CSV,
    FILENAME_UNSAFE,
    INDEX_CSV,
    COMPANIES,
    SLEEP_RANGE,
    STATE_DIR,
    STATE_FILE,
    TITLE_MAX_LEN,
)


def _resolve_column(df, canonical_name):
    """从 DataFrame 中按别名解析出规范列名对应的实际列名。"""
    aliases = COLUMN_ALIASES.get(canonical_name, [])
    for alias in aliases:
        if alias in df.columns:
            return alias
    return None


def normalize_report_df(df, stock_code, stock_name, category):
    """将 AKShare 返回的 DataFrame 规范化为统一列：title, publish_date, url。"""
    if df is None or df.empty:
        return pd.DataFrame(columns=["stock_code", "stock_name", "category", "title", "publish_date", "url", "raw_row"])

    title_col = _resolve_column(df, "title")
    date_col = _resolve_column(df, "publish_date")
    url_col = _resolve_column(df, "url")

    if not title_col:
        print(f"  [WARN] 未找到标题列，当前列: {list(df.columns)}", file=sys.stderr)
    if not date_col:
        print(f"  [WARN] 未找到日期列，当前列: {list(df.columns)}", file=sys.stderr)
    if not url_col:
        print(f"  [WARN] 未找到链接列，当前列: {list(df.columns)}", file=sys.stderr)

    n = len(df)
    out = pd.DataFrame()
    out["stock_code"] = [stock_code] * n
    out["stock_name"] = [stock_name] * n
    out["category"] = [category] * n
    out["title"] = df[title_col].astype(str).tolist() if title_col else [""] * n
    out["publish_date"] = df[date_col].astype(str).tolist() if date_col else [""] * n
    out["url"] = df[url_col].astype(str).tolist() if url_col else [""] * n
    out["raw_row"] = df.to_dict("records")
    return out


def fetch_report_list_akshare(symbol, category, start_date, end_date):
    """调用 AKShare 获取巨潮定期报告列表。返回 DataFrame 或 None。"""
    try:
        import akshare as ak
    except ImportError:
        print("请安装 akshare: pip install akshare", file=sys.stderr)
        return None

    func = getattr(ak, "stock_zh_a_disclosure_report_cninfo", None)
    if func is None:
        func = getattr(ak, "stock_report_cninfo", None)
    if func is None:
        print("当前 akshare 未找到 stock_zh_a_disclosure_report_cninfo / stock_report_cninfo，请升级: pip install akshare -U", file=sys.stderr)
        return None

    try:
        # 常见参数名：symbol/code, category, start_date, end_date（格式可能为 YYYYMMDD 或 YYYY-MM-DD）
        start_str = start_date.replace("-", "")[:8]
        end_str = end_date.replace("-", "")[:8]
        df = func(symbol=symbol, category=category, start_date=start_str, end_date=end_str)
        return df
    except Exception as e:
        print(f"  [ERROR] akshare 调用失败 symbol={symbol} category={category}: {e}", file=sys.stderr)
        return None


def random_sleep():
    import random
    t = SLEEP_RANGE[0] + random.random() * (SLEEP_RANGE[1] - SLEEP_RANGE[0])
    time.sleep(t)


def _parse_announcement_id(url):
    """从巨潮详情页 URL 解析 announcementId。"""
    from urllib.parse import urlparse, parse_qs
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        return qs.get("announcementId", [None])[0]
    except Exception:
        return None


def _parse_org_id(url):
    """从巨潮详情页 URL 解析 orgId（用于 hisAnnouncement/query 的 stock 参数）。"""
    from urllib.parse import urlparse, parse_qs
    try:
        parsed = urlparse(url)
        qs = parse_qs(parsed.query)
        return qs.get("orgId", [None])[0]
    except Exception:
        return None


# 巨潮 hisAnnouncement/query 的 category 与 column/plate
CNINFO_CATEGORY_MAP = {
    "年报": "category_ndbg_szsh",
    "半年报": "category_bndbg_szsh",
    "一季报": "category_yjdbg_szsh",
    "三季报": "category_sjdbg_szsh",
}


def _cninfo_column_plate(stock_code):
    """根据股票代码返回 (column, plate)：上交所 sse+sh，深交所 szse+sz。"""
    code = (stock_code or "").strip()
    if code.startswith("6"):
        return "sse", "sh"
    return "szse", "sz"


def fetch_cninfo_announcements(stock_code, org_id, category_cninfo, start_date, end_date):
    """
    调用巨潮 hisAnnouncement/query 获取公告列表（含 adjunctUrl）。
    返回 list of dict: announcementId, adjunctUrl, announcementTitle, announcementTime 等。
    """
    if not requests or not org_id or not category_cninfo:
        return []
    column, plate = _cninfo_column_plate(stock_code)
    # seDate 格式：YYYY-MM-DD~YYYY-MM-DD
    se_date = "{}~{}".format(
        (start_date or "")[:10].replace("/", "-"),
        (end_date or "")[:10].replace("/", "-"),
    )
    url_api = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/javascript, */*; q=0.01",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "http://www.cninfo.com.cn",
        "Referer": "http://www.cninfo.com.cn/new/disclosure/stock?stockCode={}&orgId={}".format(stock_code, org_id),
        "X-Requested-With": "XMLHttpRequest",
    }
    data = {
        "stock": "{},{}".format(stock_code, org_id),
        "tabName": "fulltext",
        "pageSize": "30",
        "pageNum": "1",
        "column": column,
        "category": category_cninfo,
        "plate": plate,
        "seDate": se_date,
        "searchkey": "",
        "secid": "",
        "sortName": "",
        "sortType": "",
        "isHLtitle": "true",
    }
    all_announcements = []
    page = 1
    while True:
        data["pageNum"] = str(page)
        try:
            r = requests.post(url_api, data=data, timeout=20, headers=headers)
            r.raise_for_status()
            body = r.json()
        except Exception as e:
            print("    [WARN] hisAnnouncement/query 请求失败: {}".format(e), file=sys.stderr)
            break
        ann_list = body.get("announcements") if isinstance(body, dict) else None
        if not ann_list:
            break
        for item in ann_list:
            if isinstance(item, dict) and item.get("adjunctUrl"):
                all_announcements.append(item)
        total_pages = int(body.get("totalpages", 1))
        if page >= total_pages:
            break
        page += 1
        random_sleep()
    return all_announcements


def build_announcement_id_to_pdf_url(to_download_rows, start_str, end_str):
    """
    根据待下载列表中的 (stock_code, orgId, category) 调用 hisAnnouncement/query，
    汇总 announcementId -> 完整 PDF URL（https://static.cninfo.com.cn/ + adjunctUrl）。
    """
    # 收集 (stock_code, org_id, category)，从 row 的 url 解析 org_id
    seen = set()
    keys_to_fetch = []
    for _, row in to_download_rows:
        url = (row.get("url") or "").strip()
        org_id = _parse_org_id(url)
        if not org_id:
            continue
        code = row.get("stock_code")
        cat = row.get("category")
        key = (code, org_id, cat)
        if key in seen:
            continue
        seen.add(key)
        cninfo_cat = CNINFO_CATEGORY_MAP.get(cat) if cat else None
        if cninfo_cat:
            keys_to_fetch.append((code, org_id, cat, cninfo_cat))

    aid_to_pdf = {}
    for stock_code, org_id, category, category_cninfo in keys_to_fetch:
        random_sleep()
        anns = fetch_cninfo_announcements(stock_code, org_id, category_cninfo, start_str, end_str)
        base = "https://static.cninfo.com.cn/"
        for a in anns:
            aid = a.get("announcementId")
            adj = a.get("adjunctUrl")
            if not aid or not adj:
                continue
            u = adj.strip()
            if u.startswith("http"):
                aid_to_pdf[str(aid)] = u
            else:
                aid_to_pdf[str(aid)] = (base + u) if not u.startswith("/") else ("https://static.cninfo.com.cn" + u)
    return aid_to_pdf


def extract_pdf_url_from_page(detail_url):
    """从详情页 HTML 或巨潮接口解析 PDF 链接。若已是 .pdf 直链则直接返回。"""
    if not detail_url or not isinstance(detail_url, str):
        return None
    s = detail_url.strip()
    if s.lower().endswith(".pdf"):
        return s
    if not requests:
        return None
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

    aid = _parse_announcement_id(s)
    if aid:
        # 1a) 尝试直接下载地址（部分站点用 GET 重定向到 PDF）
        try:
            direct = "http://www.cninfo.com.cn/new/download?announcementId={}".format(aid)
            r = requests.get(direct, timeout=15, headers=headers, allow_redirects=True)
            if r.ok and (".pdf" in r.url.lower() or (r.headers.get("Content-Type") or "").lower().find("pdf") >= 0):
                return r.url
        except Exception:
            pass
        # 1b) 尝试公告查询接口返回的 adjunctUrl
        try:
            api = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
            payload = {"announcementId": aid}
            r = requests.post(api, data=payload, timeout=15, headers=headers)
            r.raise_for_status()
            data = r.json()
            ann = None
            if isinstance(data, dict) and data.get("annList"):
                ann = data["annList"][0] if data["annList"] else None
            elif isinstance(data, dict) and data.get("adjunctUrl"):
                ann = data
            elif isinstance(data, list) and len(data) > 0:
                ann = data[0]
            if ann and isinstance(ann, dict):
                url = ann.get("adjunctUrl")
                if not url and "adjunct" in str(ann).lower():
                    for k, v in ann.items():
                        if "adjunct" in k.lower() and v and ".pdf" in str(v).lower():
                            url = v
                            break
                if url:
                    if isinstance(url, list):
                        url = url[0] if url else ""
                    url = str(url).strip()
                    if url.startswith("//"):
                        url = "https:" + url
                    elif url.startswith("/"):
                        from urllib.parse import urljoin
                        url = urljoin("http://www.cninfo.com.cn", url)
                    if url and (".pdf" in url.lower() or "pdf" in url.lower()):
                        return url
        except Exception as e:
            print("    [WARN] 巨潮 hisAnnouncement 接口失败: {}".format(e), file=sys.stderr)

    # 2) 详情页 HTML 中匹配 .pdf 或 dataclouds 等
    try:
        r = requests.get(s, timeout=15, headers=headers)
        r.raise_for_status()
        text = r.text
        m = re.search(r'["\']([^"\']+\.pdf)["\']', text, re.I)
        if m:
            url = m.group(1)
            if url.startswith("//"):
                url = "https:" + url
            elif url.startswith("/"):
                from urllib.parse import urljoin
                url = urljoin(s, url)
            return url
        m = re.search(r'(https?://[^"\']+\.pdf)', text, re.I)
        if m:
            return m.group(1)
        m = re.search(r'(https?://dataclouds\.cninfo\.com\.cn[^"\']+)', text)
        if m:
            return m.group(1)
    except Exception as e:
        print("    [WARN] 解析详情页失败 {}: {}".format(s[:50], e), file=sys.stderr)
    return None


def sanitize_filename(title):
    """去掉非法字符并截断长度。"""
    if not title or not isinstance(title, str):
        return "report"
    s = re.sub(FILENAME_UNSAFE, "_", title)
    s = s.strip().strip("_") or "report"
    return s[:TITLE_MAX_LEN]


def unique_key(row):
    """生成唯一键用于去重。"""
    url = str(row.get("url", "") or "")
    date = str(row.get("publish_date", "") or "")[:10]
    title = str(row.get("title", "") or "")
    raw = f"{url}|{date}|{title}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def expected_local_path(row, out_dir):
    """根据 row 计算应保存的 PDF 路径（与下载时命名一致）。"""
    date_raw = (row.get("publish_date") or "").strip()[:10]
    date_clean = re.sub(r"[^\d-]", "", date_raw)[:10] or "0000-00-00"
    safe_title = sanitize_filename((row.get("title") or "").strip())
    category = row.get("category", "")
    fname = "{}_{}_{}.pdf".format(date_clean, category, safe_title)
    company_dir = out_dir / "{}_{}".format(row.get("stock_code"), row.get("stock_name"))
    return company_dir / fname


def download_pdf(url, dest_path):
    """流式下载 PDF 到 dest_path，先写 .part 再 rename。"""
    if not requests:
        return False, "requests 未安装"
    for attempt in range(DOWNLOAD_RETRIES):
        try:
            r = requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            part = dest_path + ".part"
            with open(part, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
            os.replace(part, dest_path)
            return True, None
        except Exception as e:
            if attempt < DOWNLOAD_RETRIES - 1:
                time.sleep(BACKOFF_BASE ** attempt)
            else:
                return False, str(e)
    return False, "unknown"


def load_state(state_path):
    """加载已下载记录：set of unique_key。"""
    path = Path(state_path)
    if not path.exists():
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("keys", []))
    except Exception:
        return set()


def save_state(state_path, keys):
    path = Path(state_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"keys": list(keys), "updated_at": datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)


def append_index(index_path, row_dict):
    """追加一行到 index.csv。"""
    path = Path(index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    headers = ["stock_code", "stock_name", "category", "publish_date", "title", "pdf_url", "local_path", "fetched_at"]
    write_header = not path.exists()
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        if pd is not None:
            df_one = pd.DataFrame([row_dict])
            df_one.to_csv(f, index=False, header=write_header, columns=headers)
        else:
            import csv
            w = csv.DictWriter(f, fieldnames=headers)
            if write_header:
                w.writeheader()
            w.writerow({k: row_dict.get(k, "") for k in headers})


def append_failed(failed_path, row_dict, reason):
    """追加一条失败记录到 failed.csv。"""
    path = Path(failed_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    row_dict["fail_reason"] = reason
    headers = ["stock_code", "stock_name", "category", "publish_date", "title", "url", "fail_reason"]
    write_header = not path.exists()
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        if pd is not None:
            pd.DataFrame([row_dict]).to_csv(f, index=False, header=write_header, columns=headers)
        else:
            import csv
            w = csv.DictWriter(f, fieldnames=headers)
            if write_header:
                w.writeheader()
            w.writerow({k: row_dict.get(k, "") for k in headers})


def load_all_rows_from_index(index_path, out_dir):
    """
    从 index.csv 加载已下载记录，返回与 normalize_report_df 同结构的 row 列表。
    用于快速路径：无需请求数据源即可得到 all_rows，并据此计算 to_download。
    """
    path = Path(index_path)
    if not path.exists():
        return []
    out_dir = Path(out_dir)
    rows = []
    try:
        if pd is not None:
            df = pd.read_csv(path, encoding="utf-8-sig", dtype=str)
        else:
            import csv
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                df = pd.DataFrame(list(csv.DictReader(f)))
        for _, r in df.iterrows():
            row = {
                "stock_code": str(r.get("stock_code", "")).strip(),
                "stock_name": str(r.get("stock_name", "")).strip(),
                "category": str(r.get("category", "")).strip(),
                "title": str(r.get("title", "")).strip(),
                "publish_date": str(r.get("publish_date", "")).strip()[:10],
                "url": str(r.get("pdf_url", "")).strip(),
                "local_path": str(r.get("local_path", "")).strip(),
            }
            if not row["stock_code"]:
                continue
            full_path = out_dir / row["local_path"] if row["local_path"] else expected_local_path(row, out_dir)
            row["_local_full_path"] = full_path
            rows.append(row)
    except Exception as e:
        print("    [WARN] 读取 index.csv 失败: {}".format(e), file=sys.stderr)
    return rows


def run(out_dir, years, codes_override, categories, state_path, index_path, failed_path, log_collector=None):
    """主流程：拉列表 -> 解析 PDF URL -> 下载 -> 写 state 与 index。若传入 log_collector（list），则按公司追加日志并返回。"""
    out_dir = Path(out_dir)
    state_path = Path(state_path)
    index_path = Path(index_path)
    failed_path = Path(failed_path)

    companies = [(name, code) for name, code in COMPANIES if not codes_override or code in codes_override]
    if not companies:
        print("没有可选公司，请检查 --codes 或 config.COMPANIES", file=sys.stderr)
        return [] if log_collector is not None else None

    end_date = datetime.now()
    start_date = end_date - timedelta(days=years * 365)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    downloaded = load_state(state_path)
    all_rows = []
    company_total = {}  # (code, name) -> 该公司在列表中的条数
    use_fast_path = False

    # 快速路径：若 index 存在，先仅用本地 index + state + 文件存在性算 to_download；若无待下载则跳过所有网络请求
    if index_path.exists():
        index_rows = load_all_rows_from_index(index_path, out_dir)
        if index_rows:
            to_download = []
            company_to_dl = {}
            for row in index_rows:
                key = unique_key(row)
                path = row.get("_local_full_path") or expected_local_path(row, out_dir)
                if key in downloaded and path.exists():
                    continue
                if key not in downloaded and path.exists():
                    downloaded.add(key)
                    continue
                to_download.append((key, row))
                code, name = row.get("stock_code"), row.get("stock_name")
                company_to_dl[(code, name)] = company_to_dl.get((code, name), 0) + 1
            for row in index_rows:
                code, name = row.get("stock_code"), row.get("stock_name")
                company_total[(code, name)] = company_total.get((code, name), 0) + 1
            if not to_download:
                all_rows = index_rows
                use_fast_path = True
                skipped_total = len(index_rows)
                print("[report_fetcher] 快速路径: 使用 index.csv，本地文件均已存在，跳过网络请求", file=sys.stderr)
                print("[report_fetcher] 列表共 {} 条, 全部已下载(跳过), 待下载 0 条".format(len(all_rows)), file=sys.stderr)
                for (stock_code, stock_name) in company_total:
                    total = company_total.get((stock_code, stock_name), 0)
                    print("  [{} {}] 列表 {} 条 -> 跳过 {} 条(已下载过), 待下载 0 条".format(stock_code, stock_name, total, total), file=sys.stderr)
                print("", file=sys.stderr)

    if not use_fast_path:
        print("[report_fetcher] 开始拉取列表: 近 {} 年, 报告类型 {}".format(years, categories), file=sys.stderr)
        print("[report_fetcher] 已存在 state 中的记录数: {} (跳过=之前已下载过, 不重复下)".format(len(downloaded)), file=sys.stderr)

        for stock_name, stock_code in companies:
            company_dir = out_dir / f"{stock_code}_{stock_name}"
            company_dir.mkdir(parents=True, exist_ok=True)
            company_total[(stock_code, stock_name)] = 0

            for category in categories:
                random_sleep()
                df = fetch_report_list_akshare(stock_code, category, start_str, end_str)
                if df is None or df.empty:
                    continue
                norm = normalize_report_df(df, stock_code, stock_name, category)
                for _, row in norm.iterrows():
                    all_rows.append(row)
                    company_total[(stock_code, stock_name)] = company_total.get((stock_code, stock_name), 0) + 1

        # 去重：仅当 state 中有记录且本地文件存在时才跳过，否则重新下载
        to_download = []
        company_to_dl = {}
        for row in all_rows:
            key = unique_key(row)
            if key in downloaded:
                path = expected_local_path(row, out_dir)
                if path.exists():
                    continue
                downloaded.discard(key)
                print("[report_fetcher] 状态有记录但本地无文件，将重新下载: {} {}".format(row.get("stock_code"), row.get("stock_name")), file=sys.stderr)
            to_download.append((key, row))
            code, name = row.get("stock_code"), row.get("stock_name")
            company_to_dl[(code, name)] = company_to_dl.get((code, name), 0) + 1

        skipped_total = len(all_rows) - len(to_download)
        print("[report_fetcher] 列表共 {} 条, 其中已在 state 中(跳过) {} 条, 本次待下载 {} 条".format(len(all_rows), skipped_total, len(to_download)), file=sys.stderr)
        for (stock_code, stock_name) in company_total:
            total = company_total.get((stock_code, stock_name), 0)
            to_dl = company_to_dl.get((stock_code, stock_name), 0)
            sk = max(0, total - to_dl)
            print("  [{} {}] 列表 {} 条 -> 跳过 {} 条(已下载过), 待下载 {} 条".format(stock_code, stock_name, total, sk, to_dl), file=sys.stderr)
        print("", file=sys.stderr)

    company_downloaded = {}
    company_failed = {}

    if not use_fast_path:
        skipped_total = len(all_rows) - len(to_download)
        print("[report_fetcher] 列表共 {} 条, 其中已在 state 中(跳过) {} 条, 本次待下载 {} 条".format(len(all_rows), skipped_total, len(to_download)), file=sys.stderr)
        for (stock_code, stock_name) in company_total:
            total = company_total.get((stock_code, stock_name), 0)
            to_dl = company_to_dl.get((stock_code, stock_name), 0)
            sk = max(0, total - to_dl)
            print("  [{} {}] 列表 {} 条 -> 跳过 {} 条(已下载过), 待下载 {} 条".format(stock_code, stock_name, total, sk, to_dl), file=sys.stderr)
        print("", file=sys.stderr)

    # 仅在有待下载时请求巨潮接口并执行下载
    aid_to_pdf = {}
    if to_download:
        aid_to_pdf = build_announcement_id_to_pdf_url(to_download, start_str, end_str)
        if aid_to_pdf:
            print("[report_fetcher] 已从巨潮接口解析 {} 条 PDF 链接".format(len(aid_to_pdf)), file=sys.stderr)

    for key, row in to_download:
        title = (row.get("title") or "").strip()
        date_raw = (row.get("publish_date") or "").strip()[:10]
        url = (row.get("url") or "").strip()

        code, name = row.get("stock_code"), row.get("stock_name")
        if url.lower().endswith(".pdf"):
            pdf_url = url
        else:
            aid = _parse_announcement_id(url)
            pdf_url = aid_to_pdf.get(str(aid)) if aid else None
            if not pdf_url:
                pdf_url = extract_pdf_url_from_page(url)
        if not pdf_url:
            company_failed[(code, name)] = company_failed.get((code, name), 0) + 1
            print("[report_fetcher] 解析失败(无PDF链接): {} {} - {}".format(code, name, title[:50]), file=sys.stderr)
            append_failed(failed_path, {
                "stock_code": code,
                "stock_name": name,
                "category": row.get("category"),
                "publish_date": date_raw,
                "title": title,
                "url": url,
            }, "无法解析 PDF 链接")
            continue

        safe_title = sanitize_filename(title)
        date_clean = re.sub(r"[^\d-]", "", date_raw)[:10] or "0000-00-00"
        fname = f"{date_clean}_{row.get('category', '')}_{safe_title}.pdf"
        company_dir = out_dir / f"{row['stock_code']}_{row['stock_name']}"
        local_path = company_dir / fname
        local_path.parent.mkdir(parents=True, exist_ok=True)

        ok, err = download_pdf(pdf_url, str(local_path))
        random_sleep()
        if not ok:
            company_failed[(code, name)] = company_failed.get((code, name), 0) + 1
            print("[report_fetcher] 下载失败: {} {} - {}".format(code, name, err or "下载失败"), file=sys.stderr)
            append_failed(failed_path, {
                "stock_code": code,
                "stock_name": name,
                "category": row.get("category"),
                "publish_date": date_raw,
                "title": title,
                "url": pdf_url,
            }, err or "下载失败")
            continue

        company_downloaded[(code, name)] = company_downloaded.get((code, name), 0) + 1
        downloaded.add(key)
        rel_path = os.path.relpath(local_path, start=out_dir)
        print("[report_fetcher] 已下载: {} {} -> {}".format(code, name, rel_path), file=sys.stderr)
        append_index(index_path, {
            "stock_code": code,
            "stock_name": name,
            "category": row.get("category"),
            "publish_date": date_clean,
            "title": title,
            "pdf_url": pdf_url,
            "local_path": rel_path,
            "fetched_at": datetime.now().isoformat(),
        })

    save_state(state_path, downloaded)
    print("[report_fetcher] 状态已保存, 累计已下载 {} 条, 索引: {}".format(len(downloaded), index_path), file=sys.stderr)

    # 按公司生成日志条目
    if log_collector is not None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for (stock_code, stock_name) in company_total:
            total = company_total.get((stock_code, stock_name), 0)
            to_dl = company_to_dl.get((stock_code, stock_name), 0)
            downloaded_n = company_downloaded.get((stock_code, stock_name), 0)
            failed_n = company_failed.get((stock_code, stock_name), 0)
            skipped = max(0, total - to_dl)
            if failed_n > 0 and downloaded_n == 0:
                status = "失败"
            elif failed_n > 0:
                status = "部分成功"
            else:
                status = "成功"
            msg = f"新增 {downloaded_n}，跳过 {skipped}，失败 {failed_n}"
            log_collector.append({
                "stock_code": stock_code,
                "stock_name": stock_name,
                "status": status,
                "message": msg,
                "downloaded": downloaded_n,
                "failed": failed_n,
                "skipped": skipped,
                "timestamp": ts,
            })
        return log_collector
    return None


def main():
    parser = argparse.ArgumentParser(description="AKShare 抓取巨潮定期报告 PDF 到本地")
    parser.add_argument("--years", type=int, default=DEFAULT_YEARS, help=f"拉取近 N 年，默认 {DEFAULT_YEARS}")
    parser.add_argument("--out", type=str, default=DEFAULT_OUT_DIR, help=f"输出目录，默认 {DEFAULT_OUT_DIR}")
    parser.add_argument("--codes", type=str, default="", help="可选覆盖公司代码，逗号分隔，如 003010,605136")
    parser.add_argument("--categories", type=str, default=",".join(DEFAULT_CATEGORIES), help="报告类型，逗号分隔")
    args = parser.parse_args()

    # 项目根目录 = 当前工作目录（建议在 report_fetcher 下运行）
    root = Path.cwd()
    out_dir = root / args.out
    state_dir = root / STATE_DIR
    state_path = state_dir / STATE_FILE
    index_path = root / INDEX_CSV
    failed_path = root / FAILED_CSV

    codes_override = [c.strip() for c in args.codes.split(",") if c.strip()] if args.codes else None
    categories = [c.strip() for c in args.categories.split(",") if c.strip()]

    run(
        out_dir=out_dir,
        years=args.years,
        codes_override=codes_override,
        categories=categories,
        state_path=state_path,
        index_path=index_path,
        failed_path=failed_path,
    )


if __name__ == "__main__":
    main()
