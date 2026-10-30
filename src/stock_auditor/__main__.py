"""允许 ``python -m stock_auditor`` 调用命令行。"""

from stock_auditor.cli import app

if __name__ == "__main__":
    app()
