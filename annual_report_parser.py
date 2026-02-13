# -*- coding: utf-8 -*-
"""
年报全文解析：一套主正则 + 上交所/深交所兼容 +「调整后」分支。
策略：5 家公司用同一套主正则；区分 SSE/SZSE（深交所多「（元）」）；青木等「调整前/后」走表格解析取调整后列。
"""
import re
from pathlib import Path

# 与 report_parser 的 RECORD_INDICATOR_KEYS 对齐；多一个 total_equity（净资产）供后续用
OUTPUT_KEYS = [
    "revenue", "net_profit", "net_profit_deducted",
    "operating_cash_flow", "total_assets", "total_equity",
    "roe_pct", "gross_margin_pct", "net_margin_pct",
    "debt_ratio_pct", "asset_turnover", "cash_and_equivalents",
]

# 主正则：指标名 + 可选「（元）」+ 空白 + 第一个数字（当年列）。深交所带（元），上交所不带。
# 抓取「第一个」数字，对应近三年表中的当年。
_UNIT_OPT = r"(?:（元）)?"
_NUM = r"([\d,.-]+)"

# 顺序敏感：先匹配更长/更具体的（如归母净利润在净利润前）
REGEX_PATTERNS = [
    ("revenue", re.compile(r"营业收入" + _UNIT_OPT + r"\s*" + _NUM)),
    ("net_profit", re.compile(r"归属于上市公司股东的净利润" + _UNIT_OPT + r"\s*" + _NUM)),
    ("net_profit_deducted", re.compile(
        r"归属于上市公司股东的扣除非经常性损益的净利润" + _UNIT_OPT + r"\s*" + _NUM
    )),
    ("operating_cash_flow", re.compile(r"经营活动产生的现金流量净额" + _UNIT_OPT + r"\s*" + _NUM)),
    ("total_assets", re.compile(r"(?:总资产|资产总额)" + _UNIT_OPT + r"\s*" + _NUM)),
    ("total_equity", re.compile(r"归属于上市公司股东的净资产" + _UNIT_OPT + r"\s*" + _NUM)),
    ("roe_pct", re.compile(r"加权平均净资产收益率(?:（%）)?\s*" + _NUM)),
]

# 兼容旧表述（部分报告用「母公司」等）
REGEX_PATTERNS_ALT = [
    ("revenue", re.compile(r"营业总收入\s*" + _NUM)),
    ("net_profit", re.compile(r"归属于母公司(?:股东|所有者)的净利润(?:（元）)?\s*" + _NUM)),
    ("net_profit_deducted", re.compile(
        r"归属于母公司(?:股东|所有者)的扣除非经常性损益的净利润(?:（元）)?\s*" + _NUM
    )),
    ("total_assets", re.compile(r"资产总计\s*" + _NUM)),
]


def _get_pdf_text(pdf_path, max_pages=20):
    """从 PDF 前 max_pages 页提取纯文本，用于交易所判断和主正则。"""
    try:
        import pdfplumber
    except ImportError:
        return ""
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return ""
    parts = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                if i >= max_pages:
                    break
                t = page.extract_text()
                if t:
                    parts.append(t)
    except Exception:
        pass
    return "\n".join(parts)


def is_sse(text):
    """上交所：公司代码 + 上海证券交易所。"""
    if not text:
        return False
    return "上海证券交易所" in text or ("公司代码：" in text and "上交所" in text)


def is_szse(text):
    """深交所。"""
    if not text:
        return False
    return "深圳证券交易所" in text or "深交所" in text


def is_adjusted_format(text):
    """存在「调整后」列，需走表格解析取调整后列。"""
    if not text:
        return False
    return "调整后" in text and "调整前" in text


def _parse_number_raw(s):
    """把 1,728,185,916.69 或 -24,400,328.98 转为 float。"""
    if s is None:
        return None
    s = re.sub(r"[\s,，]", "", str(s).strip())
    if not s or s in ("-", "—", "－"):
        return None
    m = re.search(r"-?[\d.]+", s)
    if not m:
        return None
    try:
        return float(m.group())
    except ValueError:
        return None


def parse_standard(text, market="auto"):
    """
    在全文上跑主正则，提取 Phase1 指标。取第一个匹配到的数字（当年列）。
    market: "sse" | "szse" | "auto"（auto 时正则已兼容（元））
    """
    out = {k: None for k in OUTPUT_KEYS}
    if not text:
        return out
    for key, pat in REGEX_PATTERNS:
        m = pat.search(text)
        if m:
            raw = _parse_number_raw(m.group(1))
            if raw is not None:
                if key == "roe_pct":
                    # 报表多为 0-100 或 0-1，统一为 0-100
                    if abs(raw) <= 1.5 and "." in m.group(1):
                        raw = raw * 100
                    out[key] = round(raw, 4)
                else:
                    out[key] = raw
    for key, pat in REGEX_PATTERNS_ALT:
        if out.get(key) is not None:
            continue
        m = pat.search(text)
        if m:
            raw = _parse_number_raw(m.group(1))
            if raw is not None:
                out[key] = raw
    return out


def parse_with_table(pdf_path):
    """
    青木等「调整前/调整后」格式：解析表格，定位「调整后」列，取该列中与指标行对应的数值。
    返回与 parse_standard 相同结构的 dict。
    """
    out = {k: None for k in OUTPUT_KEYS}
    try:
        import pdfplumber
    except ImportError:
        return out
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return out
    # 指标名 -> 表头/行名中的可能写法（用于匹配行）
    row_label_to_key = [
        ("营业收入", "revenue"),
        ("归属于上市公司股东的净利润", "net_profit"),
        ("归属于母公司股东的净利润", "net_profit"),
        ("扣除非经常性损益的净利润", "net_profit_deducted"),
        ("经营活动产生的现金流量净额", "operating_cash_flow"),
        ("总资产", "total_assets"),
        ("资产总额", "total_assets"),
        ("归属于上市公司股东的净资产", "total_equity"),
        ("加权平均净资产收益率", "roe_pct"),
    ]
    try:
        with pdfplumber.open(pdf_path) as pdf:
            max_pages = min(20, len(pdf.pages))
            for page in pdf.pages[:max_pages]:
                tables = page.extract_tables()
                for table in tables:
                    if not table or len(table) < 2:
                        continue
                    # 找「调整后」列索引
                    header = table[0]
                    if not header:
                        continue
                    adj_col = None
                    for idx, cell in enumerate(header):
                        c = (cell or "").strip()
                        if "调整后" in c:
                            adj_col = idx
                            break
                    if adj_col is None:
                        continue
                    for row in table[1:]:
                        if not row:
                            continue
                        first_cell = (row[0] or "").strip()
                        for label, key in row_label_to_key:
                            if label not in first_cell:
                                continue
                            if key not in OUTPUT_KEYS or out.get(key) is not None:
                                continue
                            if adj_col < len(row):
                                val_str = (row[adj_col] or "").strip()
                                v = _parse_number_raw(val_str)
                                if v is not None:
                                    if key == "roe_pct":
                                        if abs(v) <= 1.5:
                                            v = v * 100
                                        out[key] = round(v, 4)
                                    else:
                                        out[key] = v
                            break
                    if any(out.get(k) is not None for k in ["revenue", "net_profit", "total_assets"]):
                        return out
    except Exception:
        pass
    return out


class AnnualReportParser:
    """
    年报全文解析：先判断是否「调整后」格式，再区分上交所/深交所，用同一套主正则。
    """

    def parse(self, pdf_path):
        """
        入口。返回 dict：OUTPUT_KEYS -> 数值，未提取到的为 None。
        """
        text = _get_pdf_text(pdf_path)
        if is_adjusted_format(text):
            return parse_with_table(pdf_path)
        if is_sse(text):
            return parse_standard(text, market="sse")
        if is_szse(text):
            return parse_standard(text, market="szse")
        # 未识别交易所时仍用主正则（已兼容（元））
        return parse_standard(text, market="auto")
