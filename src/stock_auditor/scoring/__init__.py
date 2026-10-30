"""量化评分：基本面 40 分、动量 20 分、总分合成。"""

from stock_auditor.scoring.composite import CompositeResult, compose_score
from stock_auditor.scoring.fundamental import (
    FundamentalResult,
    FundamentalSnapshot,
    build_snapshot,
    score_fundamentals,
)
from stock_auditor.scoring.momentum import MomentumResult, score_momentum
from stock_auditor.scoring.service import (
    QuantScore,
    store_final_scores,
    store_quant_scores,
)

__all__ = [
    "CompositeResult",
    "FundamentalResult",
    "FundamentalSnapshot",
    "MomentumResult",
    "QuantScore",
    "build_snapshot",
    "compose_score",
    "score_fundamentals",
    "score_momentum",
    "store_final_scores",
    "store_quant_scores",
]
