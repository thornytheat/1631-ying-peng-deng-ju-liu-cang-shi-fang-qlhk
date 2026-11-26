PROJECT_NAME = "影棚灯具留仓释放"
ROLE = "器材租赁预约主管"
MODEL_LABEL = "分位分箱朴素贝叶斯"
TARGET = "binary"
UNIT = "概率"
ACTION_LABEL = "加入催确认与释放队列"
RESERVE_LABEL = "当天催确认席位"
DEFAULT_DAY = 144
DEFAULT_BUDGET = 15
REPORT_LAG = 1
GROUPS = ("短片棚", "产品棚", "广告大棚", "跨城外拍")
SIGNAL_NAMES = ("payment_gap", "edit_density", "prior_delays", "lead_time")
WATCH_FEATURE = "payment_gap"
METRIC_LABEL = "Brier 分数"
FIELD_LABELS = {
    "lead_hr": "取灯前剩余 h",
    "prepay": "预付比例 %",
    "edits": "预约改动次数",
    "late_returns": "近季超时归还",
    "units": "套件灯头数",
    "replacement": "备用灯头数",
    "signed": "合同已签",
}
FIELD_BOUNDS = {
    "lead_hr": (2, 62),
    "prepay": (0, 100),
    "edits": (0, 9),
    "late_returns": (0, 12),
    "units": (1, 12),
    "replacement": (0, 8),
    "signed": (0, 1),
}
CRITICAL_FIELDS = frozenset(("lead_hr", "replacement", "signed"))
