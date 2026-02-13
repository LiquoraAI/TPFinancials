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

    # ---------- 数据 API（供看板与数据维护使用）----------
    @app.route("/api/data", methods=["GET"])
    def api_data():
        """返回 financials.json 全文（含 fetch_meta 与 records）。"""
        try:
            from data_store import load_financials
            return jsonify(load_financials())
        except Exception as e:
            return jsonify({"error": str(e), "fetch_meta": {}, "records": []}), 500

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
            # 第一步：下载 PDF
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
            try:
                from data_store import update_report_fetch_meta
                update_report_fetch_meta(run_at=run_at, success=True, entries=log_entries)
            except Exception:
                pass
            # 第二步：解析报告元数据/指标，写入 financials.json records
            parse_ok = False
            parse_msg = ""
            print("[report_parser] 第二步: 开始解析已下载 PDF，写入 financials.json ...", file=sys.stderr)
            try:
                os.chdir(PROJECT_ROOT)
                from report_parser import parse_downloaded_reports
                idx_abs = REPORT_FETCHER_DIR / INDEX_CSV
                out_abs = REPORT_FETCHER_DIR / DEFAULT_OUT_DIR
                parsed_n, failed_n, skipped_n = parse_downloaded_reports(idx_abs, out_abs)
                parse_ok = True
                parse_msg = "解析 {} 条, 复用 {} 条, 失败 {} 条".format(parsed_n, skipped_n, failed_n)
                print("[report_parser] 第二步完成: {}".format(parse_msg), file=sys.stderr)
            except Exception as e:
                parse_msg = str(e)
                print("[report_parser] 第二步失败: {}".format(e), file=sys.stderr)
            finally:
                os.chdir(cwd)
            return jsonify({
                "ok": True,
                "entries": log_entries,
                "run_at": run_at,
                "parse_ok": parse_ok,
                "parse_msg": parse_msg,
            })
        except Exception as e:
            from datetime import datetime
            run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                from data_store import update_report_fetch_meta
                update_report_fetch_meta(run_at=run_at, success=False, entries=[], error_message=str(e))
            except Exception:
                pass
            return jsonify({"ok": False, "error": str(e), "entries": [], "run_at": None}), 500
        finally:
            os.chdir(cwd)

    @app.route("/api/parse-reports", methods=["POST"])
    def api_parse_reports():
        """仅执行第二步：解析已下载 PDF 写入 financials.json。请求体可含 {"force": true} 强制重新解析全部（忽略缓存）。"""
        cwd = os.getcwd()
        force = False
        annual_only = False
        try:
            from flask import request
            data = request.get_json(silent=True) or {}
            force = data.get("force") is True
            annual_only = data.get("annual_only") is True
        except Exception:
            pass
        try:
            os.chdir(PROJECT_ROOT)
            from report_parser import parse_downloaded_reports
            from report_fetcher.config import INDEX_CSV, DEFAULT_OUT_DIR
            idx_abs = REPORT_FETCHER_DIR / INDEX_CSV
            out_abs = REPORT_FETCHER_DIR / DEFAULT_OUT_DIR
            parsed_n, failed_n, skipped_n = parse_downloaded_reports(idx_abs, out_abs, force=force, annual_only=annual_only)
            parse_msg = "解析 {} 条, 复用 {} 条, 失败 {} 条".format(parsed_n, skipped_n, failed_n)
            if force:
                parse_msg = "[强制全部重解析] " + parse_msg
            return jsonify({
                "ok": True,
                "parse_ok": True,
                "parse_msg": parse_msg,
                "parsed": parsed_n,
                "failed": failed_n,
                "skipped": skipped_n,
            })
        except Exception as e:
            return jsonify({
                "ok": False,
                "parse_ok": False,
                "parse_msg": str(e),
                "error": str(e),
            }), 500
        finally:
            os.chdir(cwd)

    @app.route("/api/parse-reports-stream", methods=["POST"])
    def api_parse_reports_stream():
        """流式重新解析：返回 text/plain 流，每行一条进度日志。请求体可含 {"force": true}。"""
        import queue
        import threading
        from flask import request, Response, stream_with_context

        force = False
        annual_only = True
        try:
            data = request.get_json(silent=True) or {}
            force = data.get("force") is True
            annual_only = data.get("annual_only", True) is True
        except Exception:
            pass
        log_queue = queue.Queue()

        def run_parser():
            cwd = os.getcwd()
            try:
                os.chdir(PROJECT_ROOT)
                from report_parser import parse_downloaded_reports
                from report_fetcher.config import INDEX_CSV, DEFAULT_OUT_DIR
                idx_abs = REPORT_FETCHER_DIR / INDEX_CSV
                out_abs = REPORT_FETCHER_DIR / DEFAULT_OUT_DIR
                parse_downloaded_reports(idx_abs, out_abs, force=force, progress_callback=log_queue.put, annual_only=annual_only)
            except Exception as e:
                log_queue.put("错误: " + str(e))
            finally:
                log_queue.put(None)
                os.chdir(cwd)

        def generate():
            thread = threading.Thread(target=run_parser)
            thread.start()
            while True:
                msg = log_queue.get()
                if msg is None:
                    break
                yield (msg + "\n").encode("utf-8")

        return Response(
            stream_with_context(generate()),
            mimetype="text/plain; charset=utf-8",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

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
