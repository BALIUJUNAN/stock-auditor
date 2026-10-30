"""配置加载。

优先级从高到低：

1. 环境变量 ``SA__分组__键``（如 ``SA__SCORE__STAR5``）
2. ``config/local/settings.local.yaml``
3. ``config/settings.yaml``

所有阈值、权重、比例必须由配置文件提供，模型不内置默认值；缺少键会直接
校验失败，避免代码里出现第二份“隐形默认值”。``.env`` 只用于密钥，不会
覆盖已有的进程环境变量。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from stock_auditor import paths

Board = Literal["sh_main", "sz_main", "chinext", "star", "bse"]
PercentileMethod = Literal["average_rank"]

SETTINGS_FILENAME = "settings.yaml"
LOCAL_SETTINGS_FILENAME = "settings.local.yaml"
INDUSTRY_PEG_FILENAME = "industry_peg.yaml"


class _ConfigModel(BaseModel):
    """配置模型的公共基类：禁止未知键，实例不可变。"""

    model_config = ConfigDict(extra="forbid", frozen=True)


class UniverseSettings(_ConfigModel):
    boards: list[Board]
    exclude_name_keywords: list[str]
    min_listing_days: int = Field(ge=0)
    exclude_sw_l1: list[str]
    focus_sw_l1: list[str]


class Stage0Settings(_ConfigModel):
    turnover_window: int = Field(ge=2)
    turnover_min: float = Field(ge=0, le=1)
    turnover_max: float = Field(ge=0, le=1)
    min_avg_amount_cny: float = Field(ge=0)
    max_suspended_days_20: int = Field(ge=0, le=20)

    @model_validator(mode="after")
    def _check_turnover_bounds(self) -> Stage0Settings:
        if self.turnover_min > self.turnover_max:
            raise ValueError("stage0.turnover_min 不能大于 stage0.turnover_max")
        return self


class CashDebtBothHighSettings(_ConfigModel):
    cash_to_assets: float = Field(ge=0, le=1)
    interest_debt_to_assets: float = Field(ge=0, le=1)


class ReceivableInflationSettings(_ConfigModel):
    growth_gap: float = Field(ge=0)
    ar_to_revenue: float = Field(ge=0, le=1)


class VetoKeywords(_ConfigModel):
    investigation: list[str] = Field(min_length=1)
    investigation_closed: list[str] = Field(min_length=1)
    regulatory_penalty: list[str] = Field(min_length=1)


class VetoSettings(_ConfigModel):
    regulatory_lookback_days: int = Field(ge=0)
    pledge_ratio_max: float = Field(ge=0, le=1)
    pledge_missing_label: str
    keywords: VetoKeywords
    cash_debt_both_high: CashDebtBothHighSettings
    receivable_inflation: ReceivableInflationSettings


class SoftDowngradeKeywords(_ConfigModel):
    cfo_or_auditor_change: list[str] = Field(min_length=1)


class SoftDowngradeSettings(_ConfigModel):
    cap: int = Field(ge=0, le=100)
    penalty_cfo_or_auditor_change: int = Field(ge=0)
    cfo_lookback_days: int = Field(ge=0)
    penalty_negative_ocf: int = Field(ge=0)
    negative_ocf_revenue_growth_min: float = Field(ge=0)
    penalty_llm_critical_risk: int = Field(ge=0)
    keywords: SoftDowngradeKeywords


class FundamentalSettings(_ConfigModel):
    min_industry_sample: int = Field(ge=1)
    history_years: int = Field(ge=1)
    imputed_discount: float = Field(ge=0, le=1)
    default_peg_cap: float = Field(gt=0)
    min_analyst_count: int = Field(ge=1)
    revenue_cagr_years: int = Field(ge=1)
    history_min_valid_days: int = Field(ge=1)
    consensus_source: str
    percentile_method: PercentileMethod


class MomentumSettings(_ConfigModel):
    overheat_r5: float = Field(ge=0)
    overheat_dev_ma20: float = Field(ge=0)
    pullback_drawdown_min: float = Field(ge=0, le=1)
    pullback_drawdown_max: float = Field(ge=0, le=1)
    shrink_volume_ratio: float = Field(ge=0)
    stabilize_rebound: float = Field(ge=0)
    breakdown_volume_ratio: float = Field(ge=0)
    breakdown_confirm_days: int = Field(ge=1)
    breakdown_lookback_days: int = Field(ge=1)
    breakdown_penalty: int = Field(ge=0)
    ma_short: int = Field(ge=2)
    ma_mid: int = Field(ge=2)
    ma_long: int = Field(ge=2)
    low_window: int = Field(ge=2)
    high_window: int = Field(ge=2)
    low_position_r20_max: float = Field(ge=0)

    @model_validator(mode="after")
    def _check_windows(self) -> MomentumSettings:
        if self.breakdown_confirm_days > self.breakdown_lookback_days:
            raise ValueError(
                "momentum.breakdown_confirm_days 不能大于 momentum.breakdown_lookback_days"
            )
        if not (self.ma_short < self.ma_mid < self.ma_long):
            raise ValueError("均线窗口必须满足 ma_short < ma_mid < ma_long")
        return self


class ScoreSettings(_ConfigModel):
    star5: int = Field(ge=0, le=100)
    star4: int = Field(ge=0, le=100)
    evidence_chain_min: int = Field(ge=0, le=100)

    @model_validator(mode="after")
    def _check_star_thresholds(self) -> ScoreSettings:
        if self.star4 > self.star5:
            raise ValueError("score.star4 不能大于 score.star5")
        return self


class SupplementSettings(_ConfigModel):
    focus_value: int = Field(ge=0)
    announcements: int = Field(ge=0)
    research_visits: int = Field(ge=0)


class FunnelSettings(_ConfigModel):
    quant_top_n: int = Field(ge=0)
    llm_pool_max: int = Field(ge=0)
    watchlist_max: int = Field(ge=0)
    supplement: SupplementSettings
    announcement_lookback_days: int = Field(ge=0)
    major_announcement_keywords: list[str] = Field(min_length=1)
    research_lookback_days: int = Field(ge=0)
    research_min_visits: int = Field(ge=0)
    research_max_r20: float = Field(ge=0)


class TokenEstimateSettings(_ConfigModel):
    cjk_chars_per_token: float = Field(gt=0)
    ascii_chars_per_token: float = Field(gt=0)
    safety_margin: float = Field(ge=0, le=1)


class LlmSettings(_ConfigModel):
    base_url: str
    tier1_model: str
    tier2_model: str
    temperature: float = Field(ge=0, le=2)
    max_retries: int = Field(ge=0)
    tier1_input_token_budget: int = Field(ge=1)
    material_lookback_days: int = Field(ge=1)
    token_estimate: TokenEstimateSettings


class ScheduleSettings(_ConfigModel):
    timezone: str
    weekly: str
    daily: str
    misfire_grace_hours: int = Field(ge=0)


class DailyWatchSettings(_ConfigModel):
    abs_change_alert: float = Field(ge=0, le=1)


class EarningsSettings(_ConfigModel):
    warn_trading_days_before: int = Field(ge=0)


class RetentionSettings(_ConfigModel):
    dossier_full_days: int = Field(ge=0)
    filter_log_days: int = Field(ge=0)


class TrackingSettings(_ConfigModel):
    horizons: list[int]
    benchmark: str
    sector_benchmarks: dict[str, str]


class BackfillSettings(_ConfigModel):
    years: int = Field(ge=1)


class CrossValidationSettings(_ConfigModel):
    max_deviation: float = Field(ge=0, le=1)
    missing_label: str
    suspect_label: str


class DataQualitySettings(_ConfigModel):
    cross_validation: CrossValidationSettings


class CommercialSettings(_ConfigModel):
    enabled: bool
    provider: str
    prefer_http: bool
    allow_windows_only_sdk: bool


class IngestSettings(_ConfigModel):
    announcement_pdf: bool
    skip_scanned_pdf: bool
    cache_by_ann_id: bool
    request_interval_seconds: float = Field(ge=0)
    max_retries: int = Field(ge=1)
    retry_backoff_seconds: float = Field(ge=0)
    daily_lookback_days: int = Field(ge=1)
    financial_periods: int = Field(ge=1)
    valuation_years: int = Field(ge=1)
    announcement_lookback_days: int = Field(ge=1)
    research_lookback_days: int = Field(ge=1)
    research_max_pages: int = Field(ge=1)
    pledge_snapshot_lookback_days: int = Field(ge=1)


class Settings(BaseSettings):
    """全部运行参数。环境变量前缀 ``SA__``，嵌套分隔符 ``__``。"""

    model_config = SettingsConfigDict(
        env_prefix="SA__",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="forbid",
        frozen=True,
    )

    universe: UniverseSettings
    stage0: Stage0Settings
    veto: VetoSettings
    soft_downgrade: SoftDowngradeSettings
    fundamental: FundamentalSettings
    momentum: MomentumSettings
    score: ScoreSettings
    funnel: FunnelSettings
    llm: LlmSettings
    schedule: ScheduleSettings
    daily_watch: DailyWatchSettings
    earnings: EarningsSettings
    retention: RetentionSettings
    tracking: TrackingSettings
    backfill: BackfillSettings
    data_quality: DataQualitySettings
    commercial: CommercialSettings
    ingest: IngestSettings

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # 环境变量最高优先级；YAML 合并结果通过 init 传入。
        return env_settings, init_settings, dotenv_settings, file_secret_settings


class PegRule(_ConfigModel):
    name: str = Field(min_length=1)
    match_sw_l2: list[str] = Field(min_length=1)
    peg_cap: float = Field(gt=0)
    revenue_cagr_min: float = Field(ge=0)


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"配置文件不存在：{path}")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"配置文件顶层必须是映射：{path}")
    return data


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def load_settings(config_dir: Path | None = None) -> Settings:
    """读取默认配置、本地覆盖与环境变量，返回校验后的配置对象。"""
    directory = Path(config_dir) if config_dir is not None else paths.config_dir()

    env_file = paths.project_root() / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)

    data = _read_yaml_mapping(directory / SETTINGS_FILENAME)
    local_file = directory / "local" / LOCAL_SETTINGS_FILENAME
    if local_file.exists():
        data = _deep_merge(data, _read_yaml_mapping(local_file))
    return Settings(**data)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内缓存的配置对象。"""
    return load_settings()


def load_industry_peg(path: Path | None = None) -> list[PegRule]:
    """读取行业 PEG 容限表。"""
    file_path = Path(path) if path is not None else paths.config_dir() / INDUSTRY_PEG_FILENAME
    with file_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, list):
        raise ValueError(f"PEG 配置顶层必须是列表：{file_path}")
    return [PegRule.model_validate(item) for item in data]
