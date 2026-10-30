"""测试公共设置。"""

from __future__ import annotations

from stock_auditor import paths

# pytest 的 --basetemp 不会自动创建多级父目录；在收集阶段先把 var/ 建好。
(paths.project_root() / "var").mkdir(parents=True, exist_ok=True)
