# -*- coding: utf-8 -*-
"""
主面板统一服务：同时提供看板静态页面 + 数据维护 API。
运行后访问 http://127.0.0.1:5000 即可使用看板与「数据维护」Tab，无需单独起 report_fetcher 服务。
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
REPORT_FETCHER_DIR = PROJECT_ROOT / "report_fetcher"


def create_app():
    try:
        from flask import Flask, send_from_directory, jsonify
    except ImportError:
        print("请安装: pip install flask", file=sys.stderr)
        sys.exit(1)

    app = Flask(__name__, static_folder=str(PROJECT_ROOT), static_url_path="")

    # ---------- 数据维护 API（须在 catch-all 之前注册）----------
    @app.route("/api/log", methods=["GET"])
    def api_log():
        cwd = os.getcwd()
        try:
            os.chdir(REPORT_FETCHER_DIR)
            if str(REPORT_FETCHER_DIR) not in sys.path:
                sys.path.insert(0, str(REPORT_FETCHER_DIR))
            from server import load_log
            return jsonify(load_log())
        finally:
            os.chdir(cwd)

    @app.route("/api/update-reports", methods=["POST"])
    def api_update_reports():
        cwd = os.getcwd()
        try:
            os.chdir(REPORT_FETCHER_DIR)
            if str(REPORT_FETCHER_DIR) not in sys.path:
                sys.path.insert(0, str(REPORT_FETCHER_DIR))
            from server import save_log
            from main import run
            from config import (
                DEFAULT_CATEGORIES,
                DEFAULT_OUT_DIR,
                DEFAULT_YEARS,
                FAILED_CSV,
                INDEX_CSV,
                STATE_DIR,
                STATE_FILE,
            )
            root = Path.cwd()
            out_dir = root / DEFAULT_OUT_DIR
            state_path = root / STATE_DIR / STATE_FILE
            index_path = root / INDEX_CSV
            failed_path = root / FAILED_CSV
            log_entries = []
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
            from datetime import datetime
            run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_log(log_entries, run_at)
            return jsonify({"ok": True, "entries": log_entries, "run_at": run_at})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e), "entries": [], "run_at": None}), 500
        finally:
            os.chdir(cwd)

    # ---------- 看板静态页面 ----------
    @app.route("/")
    def index():
        return send_from_directory(PROJECT_ROOT, "index.html")

    @app.route("/<path:path>")
    def static_file(path):
        return send_from_directory(PROJECT_ROOT, path)

    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    print(f"主面板已集成数据维护，访问 http://127.0.0.1:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
