# -*- coding: utf-8 -*-
"""
数据维护 API：提供「Update最新数据」与「获取更新日志」接口，供前端数据维护页调用。
运行方式：在 report_fetcher 目录下执行  python server.py
默认端口 5000；前端需可访问此地址（同机或配置 CORS）。
"""
import json
import os
import sys
from pathlib import Path

# 确保当前目录在 path 中，便于 import config / main
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(Path(__file__).resolve().parent)

from config import (
    DEFAULT_CATEGORIES,
    DEFAULT_OUT_DIR,
    DEFAULT_YEARS,
    FAILED_CSV,
    INDEX_CSV,
    STATE_DIR,
    STATE_FILE,
)

LOG_FILE = Path(STATE_DIR) / "last_run_log.json"


def get_log_path():
    return Path.cwd() / LOG_FILE


def load_log():
    """读取最近一次运行的日志。"""
    path = get_log_path()
    if not path.exists():
        return {"entries": [], "run_at": None}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception:
        return {"entries": [], "run_at": None}


def save_log(entries, run_at):
    """保存本次运行日志。"""
    path = get_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"entries": entries, "run_at": run_at}, f, ensure_ascii=False, indent=2)


def create_app():
    try:
        from flask import Flask, jsonify, request
        from flask_cors import CORS
    except ImportError:
        print("请安装: pip install flask flask-cors", file=sys.stderr)
        sys.exit(1)

    app = Flask(__name__)
    CORS(app, origins=["*"])

    @app.route("/api/log", methods=["GET"])
    def api_log():
        """返回最近一次更新日志（表格用）。"""
        data = load_log()
        return jsonify(data)

    @app.route("/api/update-reports", methods=["POST"])
    def api_update_reports():
        """执行一次「Update最新数据」，并返回本次各公司成功与否的日志。"""
        from main import run

        root = Path.cwd()
        out_dir = root / DEFAULT_OUT_DIR
        state_path = root / STATE_DIR / STATE_FILE
        index_path = root / INDEX_CSV
        failed_path = root / FAILED_CSV

        log_entries = []
        try:
            run(
                out_dir=out_dir,
                years=DEFAULT_YEARS,
                codes_override=None,
                categories=DEFAULT_CATEGORIES,
                state_path=state_path,
                index_path=index_path,
                failed_path=failed_path,
                log_collector=log_entries,
            )
        except Exception as e:
            return jsonify({"ok": False, "error": str(e), "entries": [], "run_at": None}), 500

        from datetime import datetime
        run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        save_log(log_entries, run_at)
        return jsonify({"ok": True, "entries": log_entries, "run_at": run_at})

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    print(f"数据维护 API 运行在 http://127.0.0.1:{port}  (GET /api/log, POST /api/update-reports)")
    app.run(host="0.0.0.0", port=port, debug=False)
