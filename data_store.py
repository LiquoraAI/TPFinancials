# -*- coding: utf-8 -*-
"""
统一数据文件 data/financials.json 的读写。
包含：抓取元信息（是否成功、最后抓取时间/版本）、以及解析后的财务记录。
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
FINANCIALS_FILE = DATA_DIR / "financials.json"


def _ensure_file():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not FINANCIALS_FILE.exists():
        default = {
            "fetch_meta": {
                "report_fetch": {
                    "success": False,
                    "last_run_at": None,
                    "version": None,
                    "message": "尚未执行过报告抓取",
                    "summary": {"downloaded": 0, "failed": 0, "skipped": 0, "companies": 0},
                }
            },
            "updated_at": None,
            "records": [],
        }
        with open(FINANCIALS_FILE, "w", encoding="utf-8") as f:
            json.dump(default, f, ensure_ascii=False, indent=2)
    return FINANCIALS_FILE


def load_financials():
    """读取完整 financials.json。"""
    _ensure_file()
    with open(FINANCIALS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_financials(data):
    """写入完整 financials.json（含 fetch_meta 与 records）。"""
    _ensure_file()
    with open(FINANCIALS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def update_report_fetch_meta(run_at, success, entries, error_message=None):
    """
    仅更新 fetch_meta.report_fetch：抓取是否成功、最后时间、版本、摘要。
    entries: 本次 run 的 log_collector 列表，每项含 downloaded, failed, skipped 等。
    """
    data = load_financials()
    if "fetch_meta" not in data:
        data["fetch_meta"] = {}
    if "report_fetch" not in data["fetch_meta"]:
        data["fetch_meta"]["report_fetch"] = {}

    rf = data["fetch_meta"]["report_fetch"]
    rf["success"] = success
    rf["last_run_at"] = run_at
    rf["version"] = run_at.replace(" ", "_").replace(":", "-") if run_at else None
    rf["message"] = error_message if error_message else ("成功" if success else "存在失败")

    total_dl = sum(e.get("downloaded", 0) for e in (entries or []))
    total_fail = sum(e.get("failed", 0) for e in (entries or []))
    total_skip = sum(e.get("skipped", 0) for e in (entries or []))
    rf["summary"] = {
        "downloaded": total_dl,
        "failed": total_fail,
        "skipped": total_skip,
        "companies": len(entries) if entries else 0,
    }

    data["updated_at"] = run_at
    save_financials(data)


def update_records_and_parse_meta(records, parsed_at, success, parsed_count, failed_count, skipped_count=0, message=None):
    """
    更新 financials.json 的 records 与 fetch_meta.parse（第二步解析的元信息）。
    skipped_count：已有指标数据、跳过 PDF 解析的条数。
    """
    data = load_financials()
    data["records"] = records
    data["updated_at"] = parsed_at
    if "fetch_meta" not in data:
        data["fetch_meta"] = {}
    data["fetch_meta"]["parse"] = {
        "success": success,
        "last_run_at": parsed_at,
        "version": parsed_at.replace(" ", "_").replace(":", "-") if parsed_at else None,
        "message": message or ("成功" if success else "存在失败"),
        "summary": {"parsed": parsed_count, "failed": failed_count, "skipped": skipped_count},
    }
    save_financials(data)
