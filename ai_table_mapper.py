# -*- coding: utf-8 -*-
"""
AI 语义对齐层：将 PDF 表格 cells 映射到标准 KPI Schema。
当规则解析未抽到关键指标时，用 LLM 理解表格语义并补全。

支持的模型（优先级从高到低，与 Liquora-chatbot 一致）：
  - Qwen / 阿里云 DashScope：设置 DASHSCOPE_API_KEY，可选 DASHSCOPE_MODEL（默认 qwen-plus）
    使用 OpenAI 兼容接口 https://dashscope.aliyuncs.com/compatible-mode/v1
  - OpenAI 云：设置 OPENAI_API_KEY，不设 base_url
  - Ollama 本地：设置 OPENAI_API_BASE 或使用默认 http://127.0.0.1:11434/v1，OPENAI_MODEL 默认 qwen2.5:7b
"""
import json
import os
import re
from pathlib import Path

# 与 Liquora-chatbot 一致：支持从 .env 读 DASHSCOPE_API_KEY 等
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# 与 report_parser.RECORD_INDICATOR_KEYS 一致
KPI_KEYS = [
    "revenue", "net_profit", "net_profit_deducted",
    "gross_margin_pct", "net_margin_pct", "roe_pct",
    "debt_ratio_pct", "asset_turnover", "total_assets", "total_equity",
    "operating_cash_flow", "cash_and_equivalents",
]

KPI_DESC = {
    "revenue": "营业收入（元）",
    "net_profit": "归属于母公司股东的净利润（元）",
    "net_profit_deducted": "扣非净利润（元）",
    "gross_margin_pct": "毛利率（%，0-100）",
    "net_margin_pct": "净利率（%，0-100）",
    "roe_pct": "净资产收益率 ROE（%，0-100）",
    "debt_ratio_pct": "资产负债率（%，0-100）",
    "asset_turnover": "总资产周转率（倍数）",
    "total_assets": "总资产（元）",
    "total_equity": "归属于母公司股东的净资产（元）",
    "operating_cash_flow": "经营活动产生的现金流量净额（元）",
    "cash_and_equivalents": "现金及现金等价物余额（元）",
}


def get_tables_from_pdf(pdf_path, max_pages=20):
    """
    从 PDF 前 max_pages 页抽取二维表格，仅做事实抽取。
    返回 list of {"page": 1-based, "cells": [[row0], [row1], ...]}
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        return []
    try:
        import pdfplumber
    except ImportError:
        return []
    result = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                if i >= max_pages:
                    break
                tables = page.extract_tables()
                for t_idx, table in enumerate(tables or []):
                    if not table:
                        continue
                    # 转成纯字符串二维表，避免 None
                    cells = [[str(c or "").strip() for c in row] for row in table]
                    if cells:
                        result.append({"page": i + 1, "table_index": t_idx, "cells": cells})
    except Exception:
        pass
    return result


def _parse_ai_number(val):
    """将 AI 返回的数值转为 float：支持 元/万/亿、百分比。"""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        if isinstance(val, bool):
            return None
        return float(val)
    s = str(val).strip()
    if not s or s.lower() in ("null", "none", "n/a", "-"):
        return None
    s = re.sub(r"[\s,，]", "", s)
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


def _get_client_and_model():
    """
    按 Liquora-chatbot 优先级返回 (OpenAI client, model_name)。
    优先 Qwen/DashScope（DASHSCOPE_API_KEY），其次 OpenAI，最后 Ollama。
    """
    try:
        from openai import OpenAI
    except ImportError:
        return None, None

    # 1) Qwen / 阿里云 DashScope（与 Liquora-chatbot 一致）
    dashscope_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if dashscope_key:
        client = OpenAI(
            api_key=dashscope_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
        model = os.environ.get("DASHSCOPE_MODEL", "qwen-plus").strip() or "qwen-plus"
        return client, model

    # 2) OpenAI 云
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    base_url = os.environ.get("OPENAI_API_BASE") or os.environ.get("OLLAMA_API_BASE")
    if api_key and not base_url:
        return OpenAI(api_key=api_key, base_url=None), os.environ.get("OPENAI_MODEL", "gpt-4o-mini")

    # 3) Ollama 本地
    base_url = (base_url or "http://127.0.0.1:11434/v1").rstrip("/")
    return OpenAI(api_key="ollama", base_url=base_url), os.environ.get("OPENAI_MODEL", "qwen2.5:7b")


def map_tables_to_kpi_with_ai(tables, period_hint=None):
    """
    用 LLM 将表格 cells 映射到标准 KPI。返回 dict: KPI_KEYS -> float | None。
    若未配置 API 或调用失败，返回空 dict。
    优先使用 Qwen（DashScope）：设置 DASHSCOPE_API_KEY、可选 DASHSCOPE_MODEL（参考 Liquora-chatbot）。
    """
    if not tables:
        return {}
    client, model = _get_client_and_model()
    if not client or not model:
        return {}

    # 限制传给 LLM 的表格大小，避免超长
    tables_small = []
    for t in tables[:10]:
        cells = t.get("cells") or []
        rows = cells[:30]
        rows = [[str(c)[:80] for c in row] for row in rows]
        tables_small.append({"page": t.get("page"), "cells": rows})

    kpi_list = "\n".join("- {}: {}".format(k, KPI_DESC.get(k, k)) for k in KPI_KEYS)
    prompt = """你是一个财务报告解析助手。下面是从上市公司年报/报告中抽取的表格（每表有 page 和 cells 二维数组）。
请根据表格内容，识别出以下指标对应的**数值**。金额类用「元」为单位（若表中为万元/亿元请换算为元）；比例类用 0-100 的数值。
若某指标在表中找不到或无法确定，该键填 null。

指标说明：
{kpi_list}

表格数据（JSON）：
{tables_json}

请只返回一个 JSON 对象，键为上述英文 key，值为数字或 null。不要其他解释。格式示例：
{{"revenue": 1728185916.69, "net_profit": -24400328.98, "gross_margin_pct": 35.5, "roe_pct": null, ...}}
""".format(
        kpi_list=kpi_list,
        tables_json=json.dumps(tables_small, ensure_ascii=False, indent=0),
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=2000,
        )
        text = (resp.choices[0].message.content or "").strip()
        # 抽取 JSON 块
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            text = text[start:end]
        data = json.loads(text)
    except Exception as e:
        if os.environ.get("TP_DEBUG"):
            print("[ai_table_mapper] LLM 调用失败: {}".format(e), flush=True)
        return {}

    out = {}
    for k in KPI_KEYS:
        v = data.get(k) if isinstance(data, dict) else None
        if v is None:
            out[k] = None
            continue
        num = _parse_ai_number(v)
        if num is not None:
            # 百分比类：若 AI 返回 0.x 则视为小数
            if k in ("gross_margin_pct", "net_margin_pct", "roe_pct", "debt_ratio_pct"):
                if -1.5 <= num <= 1.5 and num != 0:
                    num = num * 100
                if num < -200 or num > 200:
                    num = None
            out[k] = num
        else:
            out[k] = None
    return out


