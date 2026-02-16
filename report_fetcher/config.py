# -*- coding: utf-8 -*-
"""
配置：公司清单、报告类型、字段映射、默认参数。
"""

# 公司清单：名称 -> 股票代码（先写死，后续可改为从文件/API 读取）
COMPANIES = [
    ("若羽臣", "003010"),
    ("丽人丽妆", "605136"),
    ("壹网壹创", "300792"),
    ("青木科技", "301110"),
    ("凯淳股份", "301001"),
]

# 定期报告类型（AKShare category 可选值）
DEFAULT_CATEGORIES = ["一季报", "半年报", "三季报", "年报"]

# 默认拉取近年数
DEFAULT_YEARS = 5

# 默认输出目录（可改为绝对路径，如 OneDrive 下的目录）
DEFAULT_OUT_DIR = "/Users/leixu/Library/CloudStorage/OneDrive-个人/AI_experiments/TPfinancials/reports"

# 状态文件目录与文件名
STATE_DIR = "state"
STATE_FILE = "downloaded.json"

# 索引与失败记录
INDEX_CSV = "index.csv"
FAILED_CSV = "failed.csv"

# AKShare 返回列名可能变动，此处做映射（实际列名 -> 规范名）
# 常见列名：公告标题、标题、title / 公告日期、公告时间、publish_date / 公告链接、链接、url、附件链接
COLUMN_ALIASES = {
    "title": ["公告标题", "标题", "title", "报告标题"],
    "publish_date": ["公告日期", "公告时间", "日期", "publish_date", "报告日期"],
    "url": ["公告链接", "链接", "url", "详情链接", "detail_url", "附件链接", "pdf_url"],
}

# 请求限速：每次请求后睡眠范围（秒）
SLEEP_RANGE = (0.5, 1.5)

# 下载重试
DOWNLOAD_RETRIES = 3
DOWNLOAD_TIMEOUT = 60
BACKOFF_BASE = 2

# 文件名安全：替换或移除的字符
FILENAME_UNSAFE = r'[/\\:*?"<>|]'
TITLE_MAX_LEN = 80
