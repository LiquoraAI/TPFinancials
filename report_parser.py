# -*- coding: utf-8 -*-
"""
第二步：根据 index.csv 与本地 PDF 路径，解析报告元数据/指标并写入 data/financials.json 的 records。
从 PDF 中提取 PPT/看板所需指标：营业收入、净利润、扣非净利润、毛利率、净利率、ROE、资产负债率、
资产周转率、总资产、经营现金流、现金及等价物等。见 report_fetcher/pdf_indicators.md。
"""
import csv
import re
import sys
from pathlib import Path

# 看板所需指标：字段名 -> 报告表内可能出现的列名/行名（匹配其一即可）
INDICATOR_LABELS = {
    "revenue": ["营业收入", "营业总收入", "一、营业总收入"],
    "net_profit": ["净利润", "归属于母公司所有者的净利润", "五、净利润", "归属于母公司股东的净利润"],
    "net_profit_deducted": ["扣除非经常性损益后的净利润", "扣非净利润", "扣非后净利润"],
    "gross_margin_pct": ["毛利率", "销售毛利率", "营业收入毛利率"],
    "net_margin_pct": ["净利率", "销售净利率", "营业净利率"],
    "roe_pct": ["净资产收益率", "加权平均净资产收益率", "ROE", "净资产收益率（"],
    "debt_ratio_pct": ["资产负债率", "资产负债率（"],
    "asset_turnover": ["总资产周转率", "资产周转率", "总资产周转率（"],
    "total_assets": ["总资产", "资产总额", "资产总计", "三、资产总计"],
    "total_equity": ["归属于上市公司股东的净资产", "归属于母公司股东的净资产", "净资产"],
    "operating_cash_flow": ["经营活动产生的现金流量净额", "经营活动现金流量净额", "经营活动产生的现金"],
    "cash_and_equivalents": ["现金及现金等价物余额", "期末现金及现金等价物", "货币资金", "一、现金"],
}

# 所有 record 中可能出现的指标键（与 mockData/看板一致）；含 total_equity（净资产）供 Phase1 解析
RECORD_INDICATOR_KEYS = [
    "revenue", "net_profit", "net_profit_deducted",
    "gross_margin_pct", "net_margin_pct", "roe_pct",
    "debt_ratio_pct", "asset_turnover", "total_assets", "total_equity",
    "operating_cash_flow", "cash_and_equivalents",
]


def _parse_number_cell(s):
    """从单元格字符串解析数字：去逗号、空格，处理 万/亿，返回 float 或 None。"""
    if s is None or not isinstance(s, str):
        return None
    s = re.sub(r"[\s,，]", "", s.strip())
    if not s or s in ("-", "—", "－"):
        return None
    scale = 1.0
    if "亿" in s:
        s = s.replace("亿", "")
        scale = 1e8
    elif "万" in s:
        s = s.replace("万", "")
        scale = 1e4
    m = re.search(r"-?[\d.]+", s)
    if not m:
        return None
    try:
        return float(m.group()) * scale
    except ValueError:
        return None


def _parse_pct_cell(s):
    """解析百分比单元格，返回 0–100 的 float 或 None。"""
    v = _parse_number_cell(s)
    if v is None:
        return None
    if abs(v) <= 1.5 and ("," not in str(s) and "万" not in str(s) and "亿" not in str(s)):
        return round(v * 100, 4)
    return round(v, 4)


def _extract_indicators_from_pdf(pdf_path):
    """
    优先用年报解析策略（一套主正则 + 上/深交所兼容 + 调整后分支），再对未命中项用表格扫描兜底。
    返回 dict：字段名 -> 数值（元为单位的为 float，比例为 0–100 的 float），未找到为 None。
    """
    out = {k: None for k in RECORD_INDICATOR_KEYS}
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return out
    try:
        from annual_report_parser import AnnualReportParser, OUTPUT_KEYS
        annual = AnnualReportParser().parse(pdf_path)
        for k in RECORD_INDICATOR_KEYS:
            if k in OUTPUT_KEYS and annual.get(k) is not None:
                out[k] = annual[k]
    except Exception:
        pass
    try:
        import pdfplumber
    except ImportError:
        return out
    try:
        with pdfplumber.open(pdf_path) as pdf:
            # 主要财务指标表多在报告前部，限制页数以加速
            max_pages = min(20, len(pdf.pages))
            for page in pdf.pages[:max_pages]:
                tables = page.extract_tables()
                if not tables:
                    continue
                for table in tables:
                    if not table:
                        continue
                    for row in table:
                        if not row:
                            continue
                        row_text = " ".join(str(c or "").strip() for c in row)
                        for field, labels in INDICATOR_LABELS.items():
                            if field not in RECORD_INDICATOR_KEYS or out[field] is not None:
                                continue
                            for label in labels:
                                if label not in row_text:
                                    continue
                                for i, cell in enumerate(row):
                                    if not cell or label not in str(cell):
                                        continue
                                    for j, other in enumerate(row):
                                        if j == i:
                                            continue
                                        val_str = (other or "").strip()
                                        if not val_str or val_str == label:
                                            continue
                                        if field in ("gross_margin_pct", "net_margin_pct", "roe_pct", "debt_ratio_pct"):
                                            v = _parse_pct_cell(val_str)
                                        elif field == "asset_turnover":
                                            v = _parse_number_cell(val_str)
                                            if v is not None and (v > 100 or v < 0):
                                                v = None
                                        else:
                                            v = _parse_number_cell(val_str)
                                        if v is not None:
                                            out[field] = v
                                            break
                                    if out[field] is not None:
                                        break
                                if out[field] is not None:
                                    break
    except Exception as e:
        if __name__ == "__main__":
            print("    [WARN] PDF 解析异常 {}: {}".format(pdf_path.name[:30], e), file=sys.stderr)
    return out


def _period_from_date_and_category(publish_date, category):
    """从发布日期和报告类型推断期数，如 2024、2024Q1。"""
    date_str = (publish_date or "")[:10]
    year = re.sub(r"[^\d]", "", date_str)[:4]
    if not year:
        return None
    cat = (category or "").strip()
    if "一季" in cat or "一季度" in cat:
        return "{}Q1".format(year)
    if "半年" in cat:
        return "{}H1".format(year)
    if "三季" in cat or "三季度" in cat:
        return "{}Q3".format(year)
    if "年" in cat and "报" in cat and "半" not in cat and "一" not in cat and "三" not in cat:
        return year
    return year


def _record_has_indicators(rec):
    """判断 record 是否已有关键指标（有则无需再查 PDF）。"""
    if not rec or not isinstance(rec, dict):
        return False
    for key in ("revenue", "net_profit", "roe_pct"):
        if rec.get(key) is not None:
            return True
    return False


def extract_record_from_index_row(row, local_path_abs, existing_record=None):
    """
    从 index 行生成一条 record。若 existing_record 已有关键指标则复用，否则从 PDF 解析。
    """
    publish_date = (row.get("publish_date") or "").strip()[:10]
    period = _period_from_date_and_category(publish_date, row.get("category"))
    rec = {
        "stock_code": (row.get("stock_code") or "").strip(),
        "stock_name": (row.get("stock_name") or "").strip(),
        "report_type": (row.get("category") or "").strip(),
        "period": period,
        "publish_date": publish_date,
        "title": (row.get("title") or "").strip(),
        "local_path": (row.get("local_path") or "").strip(),
    }
    for k in RECORD_INDICATOR_KEYS:
        rec[k] = None
    if existing_record and _record_has_indicators(existing_record):
        for k in RECORD_INDICATOR_KEYS:
            if existing_record.get(k) is not None:
                rec[k] = existing_record[k]
    else:
        indicators = _extract_indicators_from_pdf(local_path_abs)
        for k, v in indicators.items():
            if v is not None:
                rec[k] = v
    return rec


def parse_downloaded_reports(index_path, out_dir, force=False, progress_callback=None, annual_only=False):
    """
    读取 index.csv，对每条存在本地文件的记录生成 record，去重合并后写回 financials.json。
    若 financials.json 中已有该 (stock_code, period, report_type) 且含关键指标，则跳过 PDF 解析，直接复用。
    force=True 时忽略已有指标，重新解析。
    annual_only=True 时只处理 category 为「年报」的行，结果与现有记录合并（保留季报/半年报等）。
    progress_callback(msg: str | None) 可选；每处理一条会传入进度信息，结束时传入 None。
    index_path / out_dir 建议传绝对路径。
    返回 (parsed_count, failed_count, skipped_count)。
    """
    index_path = Path(index_path)
    out_dir = Path(out_dir)
    if not index_path.exists():
        return 0, 0, 0

    def report(msg):
        if progress_callback:
            progress_callback(msg)

    # annual_only 时始终加载已有记录，以便合并后保留季报/半年报
    existing_by_key = {}
    try:
        from data_store import load_financials
        data = load_financials()
        for r in (data.get("records") or []):
            k = (r.get("stock_code"), r.get("period") or "", r.get("report_type") or "")
            existing_by_key[k] = r
    except Exception:
        pass
    if force and not annual_only:
        existing_by_key = {}

    with open(index_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)
    if annual_only:
        rows = [r for r in all_rows if (r.get("category") or "").strip() == "年报"]
        report("仅解析年报，共 {} 条（已忽略季报/半年报/三季报）".format(len(rows)))
    else:
        rows = all_rows

    records_by_key = {}
    parsed_count = 0
    failed_count = 0
    skipped_count = 0
    processed = 0
    total = len(rows)

    for row in rows:
        local_path = (row.get("local_path") or "").strip()
        if not local_path:
            failed_count += 1
            continue
        full_path = out_dir / local_path
        if not full_path.exists():
            failed_count += 1
            continue
        processed += 1
        stock_code = (row.get("stock_code") or "").strip()
        stock_name = (row.get("stock_name") or "").strip()
        publish_date = (row.get("publish_date") or "").strip()[:10]
        period = _period_from_date_and_category(publish_date, row.get("category"))
        report_type = (row.get("category") or "").strip()
        key = (stock_code, period or "", report_type)
        existing = None if force else existing_by_key.get(key)
        will_skip = not force and existing and _record_has_indicators(existing)
        report("正在处理 ({}/{}): {} {} {} {}".format(
            processed, total,
            stock_code, stock_name, period or report_type,
            "（复用缓存）" if will_skip else "（解析中）",
        ))
        try:
            rec = extract_record_from_index_row(row, full_path, existing_record=existing)
            records_by_key[key] = rec
            if will_skip:
                skipped_count += 1
            else:
                parsed_count += 1
        except Exception as e:
            failed_count += 1
            report("  失败: {}".format(e))
            if __name__ == "__main__":
                print("    [WARN] 解析行失败: {}".format(e), file=sys.stderr)

    from datetime import datetime
    parsed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if annual_only:
        for k, v in records_by_key.items():
            existing_by_key[k] = v
        records = list(existing_by_key.values())
    else:
        records = list(records_by_key.values())
    report("正在写入 financials.json ...")
    try:
        from data_store import update_records_and_parse_meta
        update_records_and_parse_meta(
            records=records,
            parsed_at=parsed_at,
            success=(failed_count == 0 or parsed_count > 0 or skipped_count > 0),
            parsed_count=parsed_count,
            failed_count=failed_count,
            skipped_count=skipped_count,
        )
        report("DONE: 解析 {} 条, 复用 {} 条, 失败 {} 条".format(parsed_count, skipped_count, failed_count))
    except Exception as e:
        report("写入失败: {}".format(e))
        print("    [WARN] 写入 financials.json 失败: {}".format(e), file=sys.stderr)
    report(None)
    return parsed_count, failed_count, skipped_count


if __name__ == "__main__":
    # 默认路径：项目根下的 report_fetcher；--force 强制重新解析所有 PDF
    force = "--force" in sys.argv or "-f" in sys.argv
    root = Path(__file__).resolve().parent
    idx = root / "report_fetcher" / "index.csv"
    out = root / "report_fetcher" / "reports"
    if force:
        print(" [--force] 忽略缓存，重新解析所有 PDF ...")
    p, f, s = parse_downloaded_reports(idx, out, force=force)
    print("parsed: {}, failed: {}, skipped(reused): {}".format(p, f, s))
