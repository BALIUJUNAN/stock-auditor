-- 0001 初始表结构。所有表均带 created_at。
-- 主键与字段按《开发任务书 v1.0》5.3 节；JSON 字段使用 DuckDB JSON 类型。

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    applied_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS stock_universe (
    code VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    board VARCHAR,
    list_date DATE,
    sw_l1 VARCHAR,
    sw_l2 VARCHAR,
    is_st BOOLEAN NOT NULL DEFAULT FALSE,
    updated_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS daily_quotes (
    code VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    volume DOUBLE,
    amount DOUBLE,
    turnover DOUBLE,
    is_suspended BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (code, trade_date)
);

CREATE TABLE IF NOT EXISTS financials (
    code VARCHAR NOT NULL,
    report_period DATE NOT NULL,
    source VARCHAR NOT NULL,
    ann_date DATE,
    revenue DOUBLE,
    net_profit_parent DOUBLE,
    ocf DOUBLE,
    total_assets DOUBLE,
    total_liab DOUBLE,
    cash DOUBLE,
    interest_debt DOUBLE,
    receivables DOUBLE,
    roe DOUBLE,
    roic DOUBLE,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (code, report_period, source)
);

CREATE TABLE IF NOT EXISTS valuation_daily (
    code VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    pe_ttm DOUBLE,
    pb DOUBLE,
    ps_ttm DOUBLE,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (code, trade_date)
);

CREATE TABLE IF NOT EXISTS consensus (
    code VARCHAR NOT NULL,
    fetch_date DATE NOT NULL,
    fiscal_year INTEGER NOT NULL,
    np_forecast DOUBLE,
    revenue_forecast DOUBLE,
    analyst_count INTEGER,
    source VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (code, fetch_date, fiscal_year)
);

CREATE TABLE IF NOT EXISTS announcements (
    ann_id VARCHAR PRIMARY KEY,
    code VARCHAR NOT NULL,
    ann_date DATE,
    title VARCHAR,
    category VARCHAR,
    url VARCHAR,
    text VARCHAR,
    text_hash VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS pledge (
    code VARCHAR NOT NULL,
    date DATE NOT NULL,
    controlling_pledge_ratio DOUBLE,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (code, date)
);

CREATE TABLE IF NOT EXISTS research_visits (
    code VARCHAR NOT NULL,
    visit_date DATE NOT NULL,
    org VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (code, visit_date, org)
);

CREATE TABLE IF NOT EXISTS earnings_calendar (
    code VARCHAR NOT NULL,
    report_period DATE NOT NULL,
    scheduled_date DATE,
    actual_date DATE,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (code, report_period)
);

CREATE TABLE IF NOT EXISTS index_daily (
    index_code VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    close DOUBLE,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (index_code, trade_date)
);

CREATE TABLE IF NOT EXISTS filter_log (
    run_id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    passed BOOLEAN NOT NULL,
    reasons JSON,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (run_id, code)
);

CREATE TABLE IF NOT EXISTS veto_events (
    run_id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    rule VARCHAR NOT NULL,
    level VARCHAR NOT NULL,
    detail VARCHAR,
    penalty DOUBLE,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (run_id, code, rule)
);

CREATE TABLE IF NOT EXISTS quant_scores (
    run_id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    raw_values JSON,
    industry_percentiles JSON,
    scores JSON,
    is_imputed JSON,
    fundamental DOUBLE,
    momentum DOUBLE,
    tags JSON,
    data_flag VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (run_id, code)
);

CREATE TABLE IF NOT EXISTS llm_pool (
    run_id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (run_id, code)
);

CREATE TABLE IF NOT EXISTS tier1_dossiers (
    run_id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    input_hash VARCHAR,
    model VARCHAR,
    prompt_version VARCHAR,
    payload JSON,
    status VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (run_id, code)
);

CREATE TABLE IF NOT EXISTS tier2_scores (
    run_id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    input_hash VARCHAR,
    model VARCHAR,
    prompt_version VARCHAR,
    tier VARCHAR,
    score DOUBLE,
    payload JSON,
    status VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (run_id, code)
);

CREATE TABLE IF NOT EXISTS final_scores (
    run_id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    raw_total DOUBLE,
    final_total DOUBLE,
    stars INTEGER,
    is_yellow BOOLEAN,
    is_veto BOOLEAN,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (run_id, code)
);

CREATE TABLE IF NOT EXISTS weekly_reports (
    run_id VARCHAR PRIMARY KEY,
    report_json JSON,
    markdown VARCHAR,
    pushed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS recommendation_tracking (
    run_id VARCHAR NOT NULL,
    code VARCHAR NOT NULL,
    rec_date DATE,
    rec_close DOUBLE,
    stars INTEGER,
    ret_t20 DOUBLE,
    alpha_t20 DOUBLE,
    ret_t60 DOUBLE,
    alpha_t60 DOUBLE,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp,
    PRIMARY KEY (run_id, code)
);

CREATE TABLE IF NOT EXISTS run_log (
    run_id VARCHAR PRIMARY KEY,
    pipeline VARCHAR NOT NULL,
    started_at TIMESTAMP,
    finished_at TIMESTAMP,
    status VARCHAR,
    step_status JSON,
    llm_tokens BIGINT,
    llm_cost DOUBLE,
    error VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS push_log (
    push_id VARCHAR PRIMARY KEY,
    run_id VARCHAR,
    channel VARCHAR,
    target VARCHAR,
    status VARCHAR,
    retries INTEGER,
    error VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT current_timestamp
);