# 数据源探测结果

> 由 `uv run python scripts/probe_akshare.py` 自动生成，生成时间：2026-10-29T23:23:09。
> 重新运行脚本会覆盖本文件；人工结论请写在 `NOTES` 常量中。

## 5.1 数据需求覆盖情况

| 数据 | 主来源 | 备用 / 校验 | 覆盖探针 | 状态 |
| --- | --- | --- | --- | --- |
| 股票列表、简称、上市日期、板块 | AKShare | 商业源 | `stock_info_a_code_name`, `stock_info_sh_name_code`, `stock_info_sh_name_code_kcb`, `stock_info_sz_name_code`, `stock_info_bj_name_code`, `stock_individual_info_em`（可选） | 可用 |
| 申万 2021 一级 / 二级行业归属 | AKShare | 商业源 | `sw_index_first_info`, `sw_index_second_info`, `sw_index_third_cons`, `stock_industry_clf_hist_sw` | 可用 |
| 日线行情（前复权）、成交量、成交额、换手率 | AKShare | 商业源 | `stock_zh_a_daily`, `stock_zh_a_hist`（可选）, `stock_zh_a_hist_tx` | 可用 |
| 财务三表与指标（含公告日） | AKShare | 商业源（交叉验证） | `stock_financial_abstract_ths`, `stock_financial_analysis_indicator_em`, `stock_balance_sheet_by_report_em`, `stock_profit_sheet_by_report_em`, `stock_cash_flow_sheet_by_report_em`, `stock_financial_report_sina_cashflow`, `stock_financial_report_sina_balance` | 可用 |
| PE / PB / PS 历史序列 | AKShare | 商业源 | `stock_zh_valuation_baidu_pe`, `stock_zh_valuation_baidu_pb`, `stock_value_em`, `stock_zh_valuation_baidu_pe_5y`（可选） | 可用 |
| 一致预期（未来 1~2 年净利润、营收） | 商业源 | — | `stock_profit_forecast_em`（可选）, `stock_profit_forecast_em_all`, `stock_profit_forecast_ths` | 可用 |
| 公告列表与正文 | AKShare（巨潮资讯 / 东财） | 商业源（正文） | `stock_zh_a_disclosure_report_cninfo`（可选）, `stock_notice_report`, `stock_individual_notice_report` | 可用 |
| 股权质押比例 | AKShare | 商业源 | `stock_gpzy_individual_pledge_ratio_detail_em`, `stock_gpzy_pledge_ratio_em` | 可用 |
| 机构调研记录 | AKShare | 商业源 | `stock_jgdy_tj_em`, `stock_jgdy_detail_em`（可选）, `em_research_visits_by_stock` | 可用 |
| 财报预约披露日期 | AKShare | 商业源 | `stock_report_disclosure` | 可用 |
| 沪深 300 与申万行业指数日线 | AKShare | — | `index_hist_sw`, `index_zh_a_hist`（可选）, `stock_zh_index_daily`, `stock_zh_index_daily_em`（可选） | 可用 |

## 接口明细

### `stock_info_a_code_name`

- 说明：A 股代码与名称列表
- 参数：无
- 覆盖数据：股票列表、简称、上市日期、板块
- 更新频率：交易所调整时（新股上市、退市、更名）；每日抓取一次即可
- 限流情况：无公开额度；建议每日一次
- 状态：可用
- 行数：5577；耗时：18.77s
- 返回字段：

```text
code, name
```

- 样例（前 2 行）：

```json
[{"code": "000001", "name": "平安银行"}, {"code": "000002", "name": "万  科Ａ"}]
```

### `stock_info_sh_name_code`

- 说明：上交所股票列表（含上市日期、板块）
- 参数：`symbol=主板A股`
- 覆盖数据：股票列表、简称、上市日期、板块
- 更新频率：交易所调整时（新股上市、退市、更名）
- 限流情况：交易所公开数据；建议每日一次
- 状态：可用
- 行数：1700；耗时：6.34s
- 返回字段：

```text
证券代码, 证券简称, 证券全称, 公司简称, 公司全称, 上市日期
```

- 样例（前 2 行）：

```json
[{"证券代码": "600000", "证券简称": "浦发银行", "证券全称": "浦发银行", "公司简称": "浦发银行", "公司全称": "上海浦东发展银行股份有限公司", "上市日期": "1999-11-10"}, {"证券代码": "600004", "证券简称": "白云机场", "证券全称": "白云机场", "公司简称": "白云机场", "公司全称": "广州白云国际机场股份有限公司", "上市日期": "2003-04-28"}]
```

### `stock_info_sh_name_code_kcb`

- 说明：上交所科创板股票列表（含上市日期）
- 参数：`symbol=科创板`
- 覆盖数据：股票列表、简称、上市日期、板块
- 更新频率：交易所调整时
- 限流情况：交易所公开数据；建议每日一次
- 状态：可用
- 行数：618；耗时：5.72s
- 返回字段：

```text
证券代码, 证券简称, 证券全称, 公司简称, 公司全称, 上市日期
```

- 样例（前 2 行）：

```json
[{"证券代码": "688001", "证券简称": "华兴源创", "证券全称": "苏州华兴源创科技", "公司简称": "华兴源创", "公司全称": "苏州华兴源创科技股份有限公司", "上市日期": "2019-07-22"}, {"证券代码": "688002", "证券简称": "睿创微纳", "证券全称": "睿创微纳", "公司简称": "睿创微纳", "公司全称": "烟台睿创微纳技术股份有限公司", "上市日期": "2019-07-22"}]
```

### `stock_info_sz_name_code`

- 说明：深交所股票列表（含上市日期、板块）
- 参数：`symbol=A股列表`
- 覆盖数据：股票列表、简称、上市日期、板块
- 更新频率：交易所调整时
- 限流情况：交易所公开数据；建议每日一次
- 状态：可用
- 行数：2905；耗时：5.48s
- 返回字段：

```text
板块, A股代码, A股简称, A股上市日期, A股总股本, A股流通股本, 所属行业
```

- 样例（前 2 行）：

```json
[{"板块": "主板", "A股代码": "000001", "A股简称": "平安银行", "A股上市日期": "1991-04-03", "A股总股本": "19,405,918,198", "A股流通股本": "19,405,684,991", "所属行业": "J 金融业"}, {"板块": "主板", "A股代码": "000002", "A股简称": "万  科Ａ", "A股上市日期": "1991-01-29", "A股总股本": "9,724,196,533", "A股流通股本": "9,716,961,890", "所属行业": "K 房地产"}]
```

### `stock_info_bj_name_code`

- 说明：北交所股票列表（含上市日期）
- 参数：无
- 覆盖数据：股票列表、简称、上市日期、板块
- 更新频率：交易所调整时
- 限流情况：交易所公开数据；建议每日一次
- 状态：可用
- 行数：354；耗时：9.47s
- 返回字段：

```text
证券代码, 证券简称, 总股本, 流通股本, 上市日期, 所属行业, 地区, 报告日期
```

- 样例（前 2 行）：

```json
[{"证券代码": "920000", "证券简称": "安徽凤凰", "总股本": 91680000, "流通股本": 57593925, "上市日期": "2020-12-23", "所属行业": "汽车制造业", "地区": "安徽省", "报告日期": "2026-10-30"}, {"证券代码": "920001", "证券简称": "纬达光电", "总股本": 153646104, "流通股本": 90052514, "上市日期": "2022-12-27", "所属行业": "计算机、通信和其他电子设备制造业", "地区": "广东省", "报告日期": "2026-10-30"}]
```

### `stock_individual_info_em`

- 说明：东财个股概况（上市时间、行业、总市值）
- 参数：`symbol=002773`
- 覆盖数据：股票列表、简称、上市日期、板块
- 更新频率：每日（上市时间固定，行业/市值随行情变化）
- 限流情况：逐只查询；建议 ≥0.5s/次
- 状态：不可用（ProxyError）
- 错误：`HTTPSConnectionPool(host='push2.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/get?fltt=2&invt=2&fields=f120%2Cf121%2Cf122%2Cf174%2Cf175%2Cf59%2Cf163%2Cf43%2Cf57%2Cf58%2Cf169%2Cf170%2Cf46%2Cf44%2Cf51%2Cf168%2Cf47%2Cf164%2Cf116%2Cf60%2Cf45%2Cf52%2Cf50%2Cf48%2Cf167%2Cf117%2Cf71%2Cf161%2Cf49%2Cf530%2Cf135%2Cf136%2Cf137%2Cf138%2Cf139%2Cf141%2Cf142%2Cf144%2Cf145%2Cf147%2Cf148%2Cf140%2Cf143%2Cf146%2Cf149%2Cf55%2Cf62%2Cf162%2Cf92%2Cf173%2Cf104%2Cf105%2Cf84%2Cf85%2Cf183%2Cf184%2`
- 耗时：3.0s

### `stock_zh_a_daily`

- 说明：新浪 A 股日线（002773，前复权）
- 参数：`symbol=sz002773`, `adjust=qfq`
- 覆盖数据：日线行情（前复权）、成交量、成交额、换手率
- 更新频率：交易日收盘后（约 15:30 起）
- 限流情况：无公开额度；建议单线程 ≥0.3s/次，全市场回填分批
- 状态：可用
- 行数：243；耗时：3.87s
- 返回字段：

```text
date, open, high, low, close, volume, amount, outstanding_share
turnover
```

- 样例（前 2 行）：

```json
[{"date": "2025-10-29", "open": 31.22, "high": 31.83, "low": 30.91, "close": 31.66, "volume": 7080610.0, "amount": 230516738.0, "outstanding_share": 686834029.0, "turnover": 0.010309055319098058}, {"date": "2025-10-30", "open": 31.66, "high": 31.68, "low": 30.79, "close": 31.3, "volume": 7008585.0, "amount": 226097238.0, "outstanding_share": 686834029.0, "turnover": 0.010204190101361445}]
```

### `stock_zh_a_hist`

- 说明：东财 A 股日线（002773，前复权；已知可能不可用）
- 参数：`symbol=002773`, `adjust=qfq`
- 覆盖数据：日线行情（前复权）、成交量、成交额、换手率
- 更新频率：交易日收盘后
- 限流情况：未知（当前环境不可达）
- 状态：不可用（ProxyError）
- 错误：`HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/kline/get?fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5%2Cf6&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf57%2Cf58%2Cf59%2Cf60%2Cf61%2Cf116&ut=7eea3edcaed734bea9cbfc24409ed989&klt=101&fqt=1&secid=0.002773&beg=20251029&end=20261029 (Caused by ProxyError('Unable to connect to proxy', RemoteDisconnected('Remote end closed connection without response')))`
- 耗时：2.84s

### `stock_zh_a_hist_tx`

- 说明：腾讯 A 股日线（002773，前复权）
- 参数：`symbol=sz002773`, `adjust=qfq`
- 覆盖数据：日线行情（前复权）、成交量、成交额、换手率
- 更新频率：交易日收盘后
- 限流情况：无公开额度；建议单线程 ≥0.3s/次
- 状态：可用
- 行数：243；耗时：4.17s
- 返回字段：

```text
date, open, close, high, low, volume, turnover, amount
```

- 样例（前 2 行）：

```json
[{"date": "2025-10-29", "open": 31.62, "close": 32.07, "high": 32.25, "low": 31.3, "volume": 7080600.0, "turnover": 0.0103, "amount": 230516699.99999997}, {"date": "2025-10-30", "open": 32.07, "close": 31.7, "high": 32.09, "low": 31.17, "volume": 7008600.0, "turnover": 0.0102, "amount": 226097200.0}]
```

### `stock_zh_valuation_baidu_pe`

- 说明：百度估值：市盈率(TTM)，近一年
- 参数：`symbol=002773`, `indicator=市盈率(TTM)`, `period=近一年`
- 覆盖数据：PE / PB / PS 历史序列
- 更新频率：交易日（收盘后更新）
- 限流情况：逐只查询；建议 ≥0.5s/次
- 状态：可用
- 行数：365；耗时：3.14s
- 返回字段：

```text
date, value
```

- 样例（前 2 行）：

```json
[{"date": "2025-10-30", "value": 23.87}, {"date": "2025-10-31", "value": 24.93}]
```

### `stock_zh_valuation_baidu_pb`

- 说明：百度估值：市净率，近一年
- 参数：`symbol=002773`, `indicator=市净率`, `period=近一年`
- 覆盖数据：PE / PB / PS 历史序列
- 更新频率：交易日（收盘后更新）
- 限流情况：逐只查询；建议 ≥0.5s/次
- 状态：可用
- 行数：365；耗时：3.28s
- 返回字段：

```text
date, value
```

- 样例（前 2 行）：

```json
[{"date": "2025-10-30", "value": 3.26}, {"date": "2025-10-31", "value": 3.4}]
```

### `stock_value_em`

- 说明：东财估值分析（002773，含 PE/PB/PS/总市值，日频）
- 参数：`symbol=002773`
- 覆盖数据：PE / PB / PS 历史序列
- 更新频率：交易日（收盘后更新）
- 限流情况：逐只查询，返回全部历史；建议 ≥0.5s/次
- 状态：可用
- 行数：2139；耗时：3.23s
- 返回字段：

```text
数据日期, 当日收盘价, 当日涨跌幅, 总市值, 流通市值, 总股本, 流通股本, PE(TTM)
PE(静), 市净率, PEG值, 市现率, 市销率
```

- 样例（前 2 行）：

```json
[{"数据日期": "2018-01-02", "当日收盘价": 59.24, "当日涨跌幅": -3.955901426719, "总市值": 39984278514.4, "流通市值": 4170696171.96, "总股本": 674954060, "流通股本": 70403379, "PE(TTM)": 66.43405927, "PE(静)": 62.06820693, "市净率": 11.283997, "PEG值": 7.30412697, "市现率": 45.24018958, "市销率": 14.23477106}, {"数据日期": "2018-01-03", "当日收盘价": 59.59, "当日涨跌幅": 0.59081701553, "总市值": 40220512435.4, "流通市值": 4195337354.61, "总股本": 674954060, "流通股本": 70403379, "PE(TTM)": 66.82656299, "PE(静)": 62.43491646, "市净率": 11.35066478, "PEG值": 7.34728099, "市现率": 45.50747632, "市销率": 14.31887251}]
```

### `stock_zh_valuation_baidu_pe_5y`

- 说明：百度估值：市盈率(TTM)，近五年
- 参数：`symbol=002773`, `indicator=市盈率(TTM)`, `period=近五年`
- 覆盖数据：PE / PB / PS 历史序列
- 更新频率：交易日（收盘后更新）
- 限流情况：逐只查询；近五年序列数据量较大，建议 ≥0.5s/次
- 状态：可用
- 行数：913；耗时：3.18s
- 返回字段：

```text
date, value
```

- 样例（前 2 行）：

```json
[{"date": "2021-10-31", "value": -85.77}, {"date": "2021-11-02", "value": -85.44}]
```

### `stock_financial_abstract_ths`

- 说明：同花顺财务摘要（002773，按报告期）
- 参数：`symbol=002773`, `indicator=按报告期`
- 覆盖数据：财务三表与指标（含公告日）
- 更新频率：定期报告披露后（一季报/半年报/三季报/年报）
- 限流情况：按报告期批量抓取；建议 ≥0.5s/次
- 状态：可用
- 行数：56；耗时：3.43s
- 返回字段：

```text
报告期, 净利润, 净利润同比增长率, 扣非净利润, 扣非净利润同比增长率, 营业总收入, 营业总收入同比增长率, 基本每股收益
每股净资产, 每股资本公积金, 每股未分配利润, 每股经营现金流, 销售净利率, 销售毛利率, 净资产收益率, 净资产收益率-摊薄
营业周期, 存货周转率, 存货周转天数, 应收账款周转天数, 流动比率, 速动比率, 保守速动比率, 产权比率
资产负债率
```

- 样例（前 2 行）：

```json
[{"报告期": "2009-12-31", "净利润": "8244.72万", "净利润同比增长率": false, "扣非净利润": "8259.29万", "扣非净利润同比增长率": false, "营业总收入": "6.38亿", "营业总收入同比增长率": false, "基本每股收益": "0.2500", "每股净资产": "1.64", "每股资本公积金": "0.07", "每股未分配利润": "1.84", "每股经营现金流": "0.33", "销售净利率": "12.92%", "销售毛利率": "89.44%", "净资产收益率": "15.30%", "净资产收益率-摊薄": "15.27%", "营业周期": "212.32", "存货周转率": "1.96", "存货周转天数": "183.63", "应收账款周转天数": "28.70", "流动比率": "1.85", "速动比率": "1.26", "保守速动比率": "1.26", "产权比率": "0.53", "资产负债率": "34.45%"}, {"报告期": "2010-12-31", "净利润": "1.09亿", "净利润同比增长率": "31.61%", "扣非净利润": "9648.51万", "扣非净利润同比增长率": "16.82%", "营业总收入": "7.96亿", "营业总收入同比增长率": "24.74%", "基本每股收益": "0.3300", "每股净资产": "1.87", "每股资本公积金": "0.07", "每股未分配利润": "2.30", "每股经营现金流": "0.41", "销售净利率": "13.63%", "销售毛利率": "89.45%", "净资产收益率": "18.27%", "净资产收益率-摊薄": "17.59%", "营业周期": "193.92", "存货周转率": "2.13", "存货周转天数": "168.86", "应收账款周转天数": "25.05", "流动比率": "1.22", "速动比率": "0.98", "保守速动比率": "0.98", "产权比率": "0.59", "资产负债率": "36.95%"}]
```

### `stock_financial_analysis_indicator_em`

- 说明：东财财务分析指标（002773，按报告期）
- 参数：`symbol=002773.SZ`, `indicator=按报告期`
- 覆盖数据：财务三表与指标（含公告日）
- 更新频率：定期报告披露后
- 限流情况：按报告期批量抓取；建议 ≥0.5s/次
- 状态：可用
- 行数：55；耗时：2.78s
- 返回字段：

```text
SECUCODE, SECURITY_CODE, SECURITY_NAME_ABBR, ORG_CODE, ORG_TYPE, REPORT_DATE, REPORT_TYPE, REPORT_DATE_NAME
SECURITY_TYPE_CODE, NOTICE_DATE, UPDATE_DATE, CURRENCY, EPSJB, EPSKCJB, EPSXS, BPS
MGZBGJ, MGWFPLR, MGJYXJJE, TOTALOPERATEREVE, MLR, PARENTNETPROFIT, KCFJCXSYJLR, TOTALOPERATEREVETZ
PARENTNETPROFITTZ, KCFJCXSYJLRTZ, YYZSRGDHBZC, NETPROFITRPHBZC, KFJLRGDHBZC, ROEJQ, ROEKCJQ, ZZCJLL
XSJLL, XSMLL, YSZKYYSR, XSJXLYYSR, JYXJLYYSR, TAXRATE, LD, SD
XJLLB, ZCFZL, QYCS, CQBL, ZZCZZTS, CHZZTS, YSZKZZTS, TOAZZL
CHZZL, YSZKZZL, TOTALDEPOSITS, GROSSLOANS, LTDRR, NEWCAPITALADER, HXYJBCZL, NONPERLOAN
BLDKBBL, NZBJE, TOTAL_ROI, NET_ROI, EARNED_PREMIUM, COMPENSATE_EXPENSE, SURRENDER_RATE_LIFE, SOLVENCY_AR
JZB, JZC, JZBJZC, ZYGPGMJZC, ZYGDSYLZQJZB, YYFXZB, JJYWFXZB, ZQZYYWFXZB
ZQCXYWFXZB, RZRQYWFXZB, EPSJBTZ, BPSTZ, MGZBGJTZ, MGWFPLRTZ, MGJYXJJETZ, ROEJQTZ
ZZCJLLTZ, ZCFZLTZ, REPORT_YEAR, ROIC, ROICTZ, NBV_LIFE, NBV_RATE, NHJZ_CURRENT_AMT
DJD_TOI_YOY, DJD_DPNP_YOY, DJD_DEDUCTDPNP_YOY, DJD_TOI_QOQ, DJD_DPNP_QOQ, DJD_DEDUCTDPNP_QOQ, XSMLL_TB, PER_TOI
PER_OI, PER_EBIT, STAFF_NUM, AVG_TOI, AVG_NET_PROFIT, PREPAID_ACCOUNTS_RATIO, ACCOUNTS_PAYABLE_TR, FIXED_ASSET_TR
CURRENT_ASSET_TR, PREPAID_ACCOUNTS_TDAYS, PAYABLE_TDAYS, OPERATE_CYCLE, GUARD_SPEED_RATIO, CASH_RATIO, INTEREST_COVERAGE_RATIO, CA_TA
NCA_TA, LIQUIDATION_RATIO, INTEREST_DEBT_RATIO, FC_LIABILITIES, FCFF_FORWARD, FCFF_BACK, SS_OI, SS_TA
NCO_OP, NCO_NETPROFIT, NCO_FIXED, FIRST_ADEQUACY_RATIO, NET_INTEREST_SPREAD, NET_INTEREST_MARGIN, LOAN_ADVANCES, NON_PERFORMING_LOAN
OVERDUE_LOANS, LOAN_PROVISION_RATIO, REVENUE_RATIO, LIABILITY, CAPITAL_PROVISIONS_SUM, RISK_COVERAGE, CAPITAL_LEVERAGE_RATIO, LIQUIDITY_COVERAGE_RATIO
NET_FUNDING_RATIO, NET_CAPITAL_LIABILITIES, NET_ASSETS_LIABILITIES, PROPRIETARY_CAPITAL, IS_BZ
```

- 样例（前 2 行）：

```json
[{"SECUCODE": "002773.SZ", "SECURITY_CODE": "002773", "SECURITY_NAME_ABBR": "康弘药业", "ORG_CODE": "10181907", "ORG_TYPE": "通用", "REPORT_DATE": "2026-09-30 00:00:00", "REPORT_TYPE": "三季报", "REPORT_DATE_NAME": "2026三季报", "SECURITY_TYPE_CODE": "058001001", "NOTICE_DATE": "2026-10-28 00:00:00", "UPDATE_DATE": "2026-10-28 00:00:00", "CURRENCY": "CNY", "EPSJB": 0.85, "EPSKCJB": null, "EPSXS": 0.85, "BPS": 10.239716325525, "MGZBGJ": 2.201640032713, "MGWFPLR": 6.482229865705, "MGJYXJJE": 0.881199828384, "TOTALOPERATEREVE": 3171579261.56, "MLR": 2812572780.98, "PARENTNETPROFIT": 784055695.42, "KCFJCXSYJLR": 791756310.12, "TOTALOPERATEREVETZ": -12.480773138793, "PARENTNETPROFITTZ": -24.092292338488, "KCFJCXSYJLRTZ": -22.654498944774, "YYZSRGDHBZC": -4.124399370922, "NETPROFITRPHBZC": -8.4064928923, "KFJLRGDHBZC": -6.970517383016, "ROEJQ": 8.34, "ROEKCJQ": null, "ZZCJLL": 7.6993043966, "XSJLL": 24.2485415393, "XSMLL": 88.6805136819, "YSZKYYSR": 1.6492474e-05, "XSJXLYYSR": 0.984006046308, "JYXJLYYSR": 0.255983709715, "TAXRATE": 16.4752289478, "LD": 11.687221488411, "SD": 11.019751733851, "XJLLB": 1.311515747143, "ZCFZL": 6.5891766608, "QYCS": 1.070539755729, "CQBL": 0.070539755729, "ZZCZZTS": 850.350353534007, "CHZZTS": 308.438369405905, "YSZKZZTS": 19.728600581, "TOAZZL": 0.317516184803, "CHZZL": 0.875377471746, "YSZKZZL": 13.685714751609, "TOTALDEPOSITS": null, "GROSSLOANS": null, "LTDRR": null, "NEWCAPITALADER": null, "HXYJBCZL": null, "NONPERLOAN": null, "BLDKBBL": null, "NZBJE": null,…（已截断）
```

### `sw_index_first_info`

- 说明：申万一级行业列表
- 参数：无
- 覆盖数据：申万 2021 一级 / 二级行业归属
- 更新频率：申万行业分类调整时（通常每年）
- 限流情况：无公开额度；建议每日一次
- 网络：直连（`NO_PROXY=*`，必要时注入系统信任库）
- 状态：可用
- 行数：31；耗时：4.59s
- 返回字段：

```text
行业代码, 行业名称, 成份个数, 静态市盈率, TTM(滚动)市盈率, 市净率, 静态股息率
```

- 样例（前 2 行）：

```json
[{"行业代码": "801010.SI", "行业名称": "农林牧渔", "成份个数": 104, "静态市盈率": 29.32, "TTM(滚动)市盈率": 33.39, "市净率": 1.85, "静态股息率": 2.33}, {"行业代码": "801030.SI", "行业名称": "基础化工", "成份个数": 413, "静态市盈率": 22.52, "TTM(滚动)市盈率": 18.57, "市净率": 2.0, "静态股息率": 1.8}]
```

### `sw_index_second_info`

- 说明：申万二级行业列表
- 参数：无
- 覆盖数据：申万 2021 一级 / 二级行业归属
- 更新频率：申万行业分类调整时（通常每年）
- 限流情况：无公开额度；建议每日一次
- 网络：直连（`NO_PROXY=*`，必要时注入系统信任库）
- 状态：可用
- 行数：131；耗时：4.6s
- 返回字段：

```text
行业代码, 行业名称, 上级行业, 成份个数, 静态市盈率, TTM(滚动)市盈率, 市净率, 静态股息率
```

- 样例（前 2 行）：

```json
[{"行业代码": "801016.SI", "行业名称": "种植业", "上级行业": "农林牧渔", "成份个数": 20, "静态市盈率": 33.14, "TTM(滚动)市盈率": 34.74, "市净率": 1.84, "静态股息率": 1.87}, {"行业代码": "801015.SI", "行业名称": "渔业", "上级行业": "农林牧渔", "成份个数": 6, "静态市盈率": 54.84, "TTM(滚动)市盈率": 52.13, "市净率": 1.51, "静态股息率": 0.61}]
```

### `sw_index_third_cons`

- 说明：申万三级行业成分（801120.SI）
- 参数：`symbol=801120.SI`
- 覆盖数据：申万 2021 一级 / 二级行业归属
- 更新频率：申万行业分类调整时（通常每年）
- 限流情况：按行业逐只查询；建议 ≥0.5s/次
- 网络：直连（`NO_PROXY=*`，必要时注入系统信任库）
- 状态：可用
- 行数：122；耗时：3.49s
- 返回字段：

```text
序号, 股票代码, 股票简称, 纳入时间, 申万1级, 细分概念, 价格, 市盈率
市盈率ttm, 市净率, ROE(%), 股息率, 市值, 近1日涨幅(2026-10-29), 近5日涨幅(2026-10-29), 今年以来涨幅(2026-10-29，基准 2025-12-31)
净利润增速(%)(2026-09-30), 营收增速(%)(2026-09-30), 上季度净利润增速(%)(2026-06-30), 上季度营收增速(%)(2026-06-30), 净利润增速差值, 营收增速差值
```

- 样例（前 2 行）：

```json
[{"序号": 1, "股票代码": "600419.SH", "股票简称": "天润乳业", "纳入时间": "2018-07-13", "申万1级": "食品饮料", "细分概念": null, "价格": 8.66, "市盈率": 65.87, "市盈率ttm": 20.65, "市净率": 1.09, "ROE(%)": 3.23, "股息率": 0.23, "市值": 27.32, "近1日涨幅(2026-10-29)": -3.13, "近5日涨幅(2026-10-29)": 3.34, "今年以来涨幅(2026-10-29，基准 2025-12-31)": -12.33, "净利润增速(%)(2026-09-30)": 855.87, "营收增速(%)(2026-09-30)": 5.39, "上季度净利润增速(%)(2026-06-30)": 348.21, "上季度营收增速(%)(2026-06-30)": 3.93, "净利润增速差值": "507.66%", "营收增速差值": "1.46%"}, {"序号": 2, "股票代码": "002330.SZ", "股票简称": "得利斯", "纳入时间": "2009-12-16", "申万1级": "食品饮料", "细分概念": null, "价格": 3.76, "市盈率": null, "市盈率ttm": null, "市净率": 1.04, "ROE(%)": 0.13, "股息率": null, "市值": 23.89, "近1日涨幅(2026-10-29)": -1.05, "近5日涨幅(2026-10-29)": -2.34, "今年以来涨幅(2026-10-29，基准 2025-12-31)": -22.31, "净利润增速(%)(2026-09-30)": -43.16, "营收增速(%)(2026-09-30)": -11.52, "上季度净利润增速(%)(2026-06-30)": -45.4, "上季度营收增速(%)(2026-06-30)": -16.97, "净利润增速差值": "2.24%", "营收增速差值": "5.45%"}]
```

### `stock_industry_clf_hist_sw`

- 说明：申万历史分类（全量）
- 参数：无
- 覆盖数据：申万 2021 一级 / 二级行业归属
- 更新频率：申万行业分类调整时（通常每年）
- 限流情况：全量接口，数据量约 1.3 万行；建议每日一次
- 网络：直连（`NO_PROXY=*`，必要时注入系统信任库）
- 状态：可用
- 行数：12929；耗时：3.82s
- 返回字段：

```text
symbol, start_date, industry_code, update_time
```

- 样例（前 2 行）：

```json
[{"symbol": "000001", "start_date": "1991-04-03", "industry_code": "440101", "update_time": "2015-10-27"}, {"symbol": "000001", "start_date": "2014-02-21", "industry_code": "480101", "update_time": "2024-09-27"}]
```

### `index_hist_sw`

- 说明：申万指数日线（801120）
- 参数：`symbol=801120`, `period=day`
- 覆盖数据：沪深 300 与申万行业指数日线
- 更新频率：交易日收盘后
- 限流情况：无公开额度；建议 ≥0.3s/次
- 网络：直连（`NO_PROXY=*`，必要时注入系统信任库）
- 状态：可用
- 行数：6481；耗时：3.42s
- 返回字段：

```text
代码, 日期, 收盘, 开盘, 最高, 最低, 成交量, 成交额
```

- 样例（前 2 行）：

```json
[{"代码": "801120", "日期": "1999-12-30", "收盘": 1000.0, "开盘": 1000.0, "最高": 1000.0, "最低": 1000.0, "成交量": 0.22650915, "成交额": 2.4228916783}, {"代码": "801120", "日期": "2000-01-04", "收盘": 1024.64, "开盘": 999.94, "最高": 1032.35, "最低": 988.37, "成交量": 0.2445959, "成交额": 2.9946705372}]
```

### `stock_zh_a_disclosure_report_cninfo`

- 说明：巨潮公告（002773，近一年）
- 参数：`symbol=002773`, `market=沪深京`
- 覆盖数据：公告列表与正文
- 更新频率：公告实时发布（盘后及披露时段）
- 限流情况：巨潮接口易被限流/返回非 JSON；需指数退避重试，建议 ≥1s/次
- 状态：不可用（JSONDecodeError）
- 错误：`Expecting value: line 1 column 1 (char 0)`
- 耗时：29.01s

### `stock_notice_report`

- 说明：东财公告（全部，昨日）
- 参数：`symbol=全部`, `date=20261028`
- 覆盖数据：公告列表与正文
- 更新频率：公告实时发布（盘后及披露时段）
- 限流情况：按日全市场查询；建议 ≥0.5s/次
- 状态：可用
- 行数：4621；耗时：18.07s
- 返回字段：

```text
代码, 名称, 公告标题, 公告类型, 公告日期, 网址
```

- 样例（前 2 行）：

```json
[{"代码": "920011", "名称": "晨光电机", "公告标题": "晨光电机:舟山晨光电机股份有限公司第二届董事会第二次会议决议公告", "公告类型": "董事会决议公告", "公告日期": "2026-10-28", "网址": "https://data.eastmoney.com/notices/detail/920011/AN202610281831115435.html"}, {"代码": "920436", "名称": "大地电气", "公告标题": "大地电气:第四届董事会第十次会议决议公告", "公告类型": "董事会决议公告", "公告日期": "2026-10-28", "网址": "https://data.eastmoney.com/notices/detail/920436/AN202610281831117494.html"}]
```

### `stock_individual_notice_report`

- 说明：东财个股公告（002773，近一年）
- 参数：`security=002773`, `symbol=全部`
- 覆盖数据：公告列表与正文
- 更新频率：公告实时发布（盘后及披露时段）
- 限流情况：按个股查询；建议 ≥0.5s/次
- 状态：可用
- 行数：139；耗时：3.66s
- 返回字段：

```text
代码, 名称, 公告标题, 公告类型, 公告日期, 网址
```

- 样例（前 2 行）：

```json
[{"代码": "002773", "名称": "康弘药业", "公告标题": "康弘药业:第八届董事会第二十一次会议决议公告", "公告类型": "董事会决议公告", "公告日期": "2026-10-28", "网址": "https://data.eastmoney.com/notices/detail/002773/AN202610271831025817.html"}, {"代码": "002773", "名称": "康弘药业", "公告标题": "康弘药业:2026年三季度报告", "公告类型": "三季度报告全文", "公告日期": "2026-10-28", "网址": "https://data.eastmoney.com/notices/detail/002773/AN202610271831025819.html"}]
```

### `stock_gpzy_individual_pledge_ratio_detail_em`

- 说明：东财个股质押明细（600664，有质押记录）
- 参数：`symbol=600664`
- 覆盖数据：股权质押比例
- 更新频率：按季度披露（以交易所/东财更新为准）
- 限流情况：按个股查询；建议 ≥0.5s/次
- 状态：可用
- 行数：10；耗时：3.06s
- 返回字段：

```text
序号, 股票代码, 股票简称, 股东名称, 质押股份数量, 占所持股份比例, 占总股本比例, 质押机构
最新价, 质押日收盘价, 预估平仓线, 质押开始日期, 质押结束日期, 状态, 公告日期
```

- 样例（前 2 行）：

```json
[{"序号": 1, "股票代码": "600664", "股票简称": "哈药股份", "股东名称": "哈药集团有限公司", "质押股份数量": 256000000, "占所持股份比例": 21.82, "占总股本比例": 10.16, "质押机构": "平安银行股份有限公司哈尔滨分行", "最新价": 5.29, "质押日收盘价": 3.19, "预估平仓线": 1.7864, "质押开始日期": "2026-06-23", "质押结束日期": "NaT", "状态": "未解押", "公告日期": "2026-06-25"}, {"序号": 2, "股票代码": "600664", "股票简称": "哈药股份", "股东名称": "哈药集团有限公司", "质押股份数量": 80000000, "占所持股份比例": 6.82, "占总股本比例": 3.18, "质押机构": "东亚银行(中国)有限公司哈尔滨分行", "最新价": 5.29, "质押日收盘价": 3.7, "预估平仓线": 2.072, "质押开始日期": "2026-04-24", "质押结束日期": "NaT", "状态": "未解押", "公告日期": "2026-04-28"}]
```

### `stock_gpzy_pledge_ratio_em`

- 说明：东财全市场质押比例（最近一个周五）
- 参数：`date=20261023`
- 覆盖数据：股权质押比例
- 更新频率：按季度披露
- 限流情况：全市场单日快照；建议每日一次
- 状态：可用
- 行数：2218；耗时：5.11s
- 返回字段：

```text
序号, 股票代码, 股票简称, 交易日期, 所属行业, 质押比例, 质押股数, 质押市值
质押笔数, 无限售股质押数, 限售股质押数, 近一年涨跌幅, 所属行业代码
```

- 样例（前 2 行）：

```json
[{"序号": 1, "股票代码": "600370", "股票简称": "*ST三房", "交易日期": "2026-10-23", "所属行业": "化学纤维", "质押比例": 78.74, "质押股数": 316745.56, "质押市值": 462448.5176, "质押笔数": 34, "无限售股质押数": 316745.56, "限售股质押数": 0.0, "近一年涨跌幅": -36.7965368, "所属行业代码": "471"}, {"序号": 2, "股票代码": "000567", "股票简称": "海德股份", "交易日期": "2026-10-23", "所属行业": "多元金融", "质押比例": 75.09, "质押股数": 146779.06, "质押市值": 786735.7616, "质押笔数": 8, "无限售股质押数": 146779.06, "限售股质押数": 0.0, "近一年涨跌幅": -22.65512266, "所属行业代码": "738"}]
```

### `stock_jgdy_tj_em`

- 说明：东财机构调研统计（近一年）
- 参数：`date=20251029`
- 覆盖数据：机构调研记录
- 更新频率：调研记录披露后（一般 T+1）
- 限流情况：按日期区间抓取；建议 ≥0.5s/次
- 状态：可用
- 行数：21434；耗时：27.63s
- 返回字段：

```text
序号, 代码, 名称, 最新价, 涨跌幅, 接待机构数量, 接待方式, 接待人员
接待地点, 接待日期, 公告日期
```

- 样例（前 2 行）：

```json
[{"序号": 1, "代码": "300476", "名称": "胜宏科技", "最新价": 148.42, "涨跌幅": -7.46, "接待机构数量": 301, "接待方式": "电话会议", "接待人员": "副总裁、董事会秘书 朱溪瑶,投资者关系经理 王慧珍", "接待地点": "进门财经线上电话会议", "接待日期": "2026-10-29", "公告日期": "2026-10-30"}, {"序号": 2, "代码": "002179", "名称": "中航光电", "最新价": 33.2, "涨跌幅": -1.04, "接待机构数量": 125, "接待方式": "业绩说明会,进门网络直播,电话会议", "接待人员": "董事长、总经理 李森,副总经理 郭建忠,总会计师、董事会秘书 王亚歌,股东与证券事务办公室主任、证券事务代表 赵丹,证券事务主管 郭涅培", "接待地点": null, "接待日期": "2026-10-29", "公告日期": "2026-10-30"}]
```

### `stock_jgdy_detail_em`

- 说明：东财机构调研明细（昨日；接口按起始日全量分页，数据量大）
- 参数：`date=20261028`
- 覆盖数据：机构调研记录
- 更新频率：调研记录披露后（一般 T+1）
- 限流情况：AKShare 包装按起始日全量分页，单日可达数百页；正式采集应改为按个股过滤
- 状态：不可用（TypeError）
- 错误：`'NoneType' object is not subscriptable`
- 耗时：19.2s

### `em_research_visits_by_stock`

- 说明：东财调研记录（按个股过滤，002773，前 50 条）
- 参数：`security_code=002773`, `page_size=50`
- 覆盖数据：机构调研记录
- 更新频率：调研记录披露后（一般 T+1）
- 限流情况：按个股分页，每页 50 条；建议每只股票只取最近 1-2 页
- 状态：可用
- 行数：50；耗时：2.91s
- 返回字段：

```text
SECUCODE, SECURITY_CODE, SECURITY_NAME_ABBR, ORG_CODE, NOTICE_DATE, RECEIVE_START_DATE, RECEIVE_END_DATE, RECEIVE_TIME_EXPLAIN
RECEIVE_OBJECT_TYPE, RECEIVE_OBJECT, OBJECT_CODE, END_DATE, SOURCE, RECEIVE_PLACE, RECEIVE_WAY, RECEIVE_WAY_EXPLAIN
INVESTIGATORS, RECEPTIONIST, REMARK, NUM, CONTENT, IS_MAX_REPORT, EUTIME, LISTING_STATE
SUM, ORG_TYPE, ORG_NAME, EITIME, ORG_TYPE_CODE, IS_SOURCE, NUMBERNEW, IS_QFII
URL, FILE_EXTENSION
```

- 样例（前 2 行）：

```json
[{"SECUCODE": "002773.SZ", "SECURITY_CODE": "002773", "SECURITY_NAME_ABBR": "康弘药业", "ORG_CODE": "10181907", "NOTICE_DATE": "2026-09-11 00:00:00", "RECEIVE_START_DATE": "2026-09-11 00:00:00", "RECEIVE_END_DATE": "2026-09-11 00:00:00", "RECEIVE_TIME_EXPLAIN": "2026年9月11日(周五)15:00-17:00", "RECEIVE_OBJECT_TYPE": "003", "RECEIVE_OBJECT": "投资者网上提问", "OBJECT_CODE": null, "END_DATE": "2026-09-11 00:00:00", "SOURCE": "007", "RECEIVE_PLACE": "公司通过全景网“投资者关系互动平台”(https://ir.p5w.net)采用网络远程的方式召开业绩说明会", "RECEIVE_WAY": "004,008", "RECEIVE_WAY_EXPLAIN": "业绩说明会,书面", "INVESTIGATORS": null, "RECEPTIONIST": "董事、总裁 柯潇,独立董事 周德敏,独立董事 邓宏光,独立董事 许楠,副总裁、财务总监 钟建军,董事会秘书 邓康", "REMARK": null, "NUM": 1, "CONTENT": "公司就投资者在本次说明会中提出的问题进行了回复:\r\n\r\n1、问:康柏西普ROP适应症已经获批,目前医院进院、市场推广的实际进展如何?对今年及明年的销售增量有怎样的判断?公司如何看待该适应症后续医保谈判的前景?\r\n\r\n答:尊敬的投资者,您好!康柏西普眼用注射液(商品名:朗沐)是公司全资子公司康弘生物自主研发的1类生物创新药,2026年9月收到中国药品监督管理局签发的增加适应症的《药品注册证书》,用于治疗早产儿视网膜病变(ROP)和AP-ROP(急进性后极部ROP),是该产品获批的第五项适应症。本次该产品新增适应症,将更进一步惠及广大患者,满足临床的用药需求。由于药品的销售可能受到国家政策、市场环境变化等因素影响,存在不确定性,敬请广大投资者谨慎决策,注意投资风险。感谢您的关注与支持!\r\n\r\n2、问:公司新增4个基药目录的药品,是否已开始布局销售等工作?\r\n\r\n答:尊敬的投资者,您好!2026年7月,公司及公司子公司共14个主要在销产品纳入《国家基本药物目录(2026年版)》,其中,康柏西普眼用注射液预充式、舒肝解郁胶囊、右佐匹克隆片(伊坦宁)、枸橼酸托法替布缓释片(诺泰欣)为本次新增纳入产品。新版《国家基本药物目录》自2026年9月1日起施行,有利于该品种在各级医疗机构的推广使用,对公司市场拓展及长远发展将产生积极影响。但药品后续的具体销售情况受行业政策、市场环境、临床需求及竞争格局等多重因素影响,存在不确定性。感谢您的关注与支持!\r\n\r\n3、问:KH631、KH658基因治疗项目的Ⅱ期主要数据预计什么时候对外披露?进入Ⅲ期临床的时间规划,以及对外BD合作的思路?\r\n\r\n答:尊敬的投资者,您好!KH631眼用注射液和KH658眼用注射液均已完成中国临床Ⅱ期、美国临床I期入组,将于2026年内获得Ⅱ期临床试验主要数据,并积极与国家药品监督管理局药…（已截断）
```

### `stock_report_disclosure`

- 说明：财报预约披露时间（2026三季）
- 参数：`market=沪深京`, `period=2026三季`
- 覆盖数据：财报预约披露日期
- 更新频率：披露日程更新时（财报季前后）
- 限流情况：建议每日一次
- 状态：可用
- 行数：5581；耗时：3.7s
- 返回字段：

```text
股票代码, 股票简称, 首次预约, 初次变更, 二次变更, 三次变更, 实际披露
```

- 样例（前 2 行）：

```json
[{"股票代码": "000001", "股票简称": "平安银行", "首次预约": "2026-10-24", "初次变更": "NaT", "二次变更": "NaT", "三次变更": "NaT", "实际披露": "2026-10-24"}, {"股票代码": "000002", "股票简称": "万  科Ａ", "首次预约": "2026-10-30", "初次变更": "NaT", "二次变更": "NaT", "三次变更": "NaT", "实际披露": "2026-10-30"}]
```

### `index_zh_a_hist`

- 说明：东财指数日线（000300）
- 参数：`symbol=000300`
- 覆盖数据：沪深 300 与申万行业指数日线
- 更新频率：交易日收盘后
- 限流情况：未知（当前环境不可达）
- 状态：不可用（ProxyError）
- 错误：`HTTPSConnectionPool(host='80.push2.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/clist/get?pn=1&pz=100&po=1&np=1&ut=bd1d9ddb04089700cf9c27f6f7426281&fltt=2&invt=2&fid=f3&fs=b%3AMK0010%2Cm%3A1%2Bt%3A1%2Cm%3A0+t%3A5%2Cm%3A1%2Bs%3A3%2Cm%3A0%2Bt%3A5%2Cm%3A2&fields=f3%2Cf12%2Cf13 (Caused by ProxyError('Unable to connect to proxy', RemoteDisconnected('Remote end closed connection without response')))`
- 耗时：8.31s

### `stock_zh_index_daily`

- 说明：新浪指数日线（sh000300）
- 参数：`symbol=sh000300`
- 覆盖数据：沪深 300 与申万行业指数日线
- 更新频率：交易日收盘后
- 限流情况：无公开额度；建议 ≥0.3s/次
- 状态：可用
- 行数：6019；耗时：3.3s
- 返回字段：

```text
date, open, high, low, close, volume
```

- 样例（前 2 行）：

```json
[{"date": "2002-01-04", "open": 1316.455, "high": 1316.455, "low": 1316.455, "close": 1316.455, "volume": 0}, {"date": "2002-01-07", "open": 1302.084, "high": 1302.084, "low": 1302.084, "close": 1302.084, "volume": 0}]
```

### `stock_zh_index_daily_em`

- 说明：东财指数日线（sh000300）
- 参数：`symbol=sh000300`
- 覆盖数据：沪深 300 与申万行业指数日线
- 更新频率：交易日收盘后
- 限流情况：未知（当前环境不可达）
- 状态：不可用（ProxyError）
- 错误：`HTTPSConnectionPool(host='push2his.eastmoney.com', port=443): Max retries exceeded with url: /api/qt/stock/kline/get?secid=1.000300&fields1=f1%2Cf2%2Cf3%2Cf4%2Cf5&fields2=f51%2Cf52%2Cf53%2Cf54%2Cf55%2Cf56%2Cf57%2Cf58&klt=101&fqt=0&beg=20251029&end=20261029 (Caused by ProxyError('Unable to connect to proxy', RemoteDisconnected('Remote end closed connection without response')))`
- 耗时：2.98s

### `tool_trade_date_hist_sina`

- 说明：新浪交易日历
- 参数：无
- 更新频率：未确认
- 限流情况：未确认
- 状态：可用
- 行数：8797；耗时：2.79s
- 返回字段：

```text
trade_date
```

- 样例（前 2 行）：

```json
[{"trade_date": "1990-12-19"}, {"trade_date": "1990-12-20"}]
```

### `stock_profit_forecast_em`

- 说明：东财一致预期（002773；已知可能报错）
- 参数：`symbol=002773`
- 覆盖数据：一致预期（未来 1~2 年净利润、营收）
- 更新频率：机构预测更新时（不定期）
- 限流情况：按代码查询在 AKShare 1.20.6 报错；改用无参全量接口后本地过滤
- 状态：不可用（TypeError）
- 错误：`'NoneType' object is not subscriptable`
- 耗时：2.86s

### `stock_profit_forecast_em_all`

- 说明：东财一致预期（无参，全市场）
- 参数：无
- 覆盖数据：一致预期（未来 1~2 年净利润、营收）
- 更新频率：机构预测更新时（不定期）
- 限流情况：全市场数据量大；建议每周快照
- 状态：可用
- 行数：2824；耗时：6.58s
- 返回字段：

```text
序号, 代码, 名称, 研报数, 机构投资评级(近六个月)-买入, 机构投资评级(近六个月)-增持, 机构投资评级(近六个月)-中性, 机构投资评级(近六个月)-减持
机构投资评级(近六个月)-卖出, 2025预测每股收益, 2026预测每股收益, 2027预测每股收益, 2028预测每股收益
```

- 样例（前 2 行）：

```json
[{"序号": 1, "代码": "600519", "名称": "贵州茅台", "研报数": 39, "机构投资评级(近六个月)-买入": 30.0, "机构投资评级(近六个月)-增持": 9.0, "机构投资评级(近六个月)-中性": 0.0, "机构投资评级(近六个月)-减持": 0.0, "机构投资评级(近六个月)-卖出": 0.0, "2025预测每股收益": 65.851754826108, "2026预测每股收益": 67.175384615385, "2027预测每股收益": 71.193333333333, "2028预测每股收益": 75.301052631579}, {"序号": 2, "代码": "605499", "名称": "东鹏饮料", "研报数": 38, "机构投资评级(近六个月)-买入": 28.0, "机构投资评级(近六个月)-增持": 10.0, "机构投资评级(近六个月)-中性": 0.0, "机构投资评级(近六个月)-减持": 0.0, "机构投资评级(近六个月)-卖出": 0.0, "2025预测每股收益": 6.01371192761, "2026预测每股收益": 7.365894736842, "2027预测每股收益": 8.410631578947, "2028预测每股收益": 9.57772972973}]
```

### `stock_profit_forecast_ths`

- 说明：同花顺一致预期（002773，预测年报每股收益）
- 参数：`symbol=002773`, `indicator=预测年报每股收益`
- 覆盖数据：一致预期（未来 1~2 年净利润、营收）
- 更新频率：机构预测更新时（不定期）
- 限流情况：开源接口；建议每周快照
- 状态：可用
- 行数：3；耗时：3.25s
- 返回字段：

```text
年度, 预测机构数, 最小值, 均值, 最大值, 行业平均数
```

- 样例（前 2 行）：

```json
[{"年度": "2026", "预测机构数": 6, "最小值": 1.08, "均值": 1.22, "最大值": 1.41, "行业平均数": 1.39}, {"年度": "2027", "预测机构数": 6, "最小值": 1.24, "均值": 1.34, "最大值": 1.53, "行业平均数": 1.53}]
```

### `stock_balance_sheet_by_report_em`

- 说明：东财资产负债表（SZ002773，按报告期）
- 参数：`symbol=SZ002773`
- 覆盖数据：财务三表与指标（含公告日）
- 更新频率：定期报告披露后
- 限流情况：按报告期批量抓取；建议 ≥0.5s/次
- 状态：可用
- 行数：52；耗时：9.43s
- 返回字段：

```text
SECUCODE, SECURITY_CODE, SECURITY_NAME_ABBR, ORG_CODE, ORG_TYPE, REPORT_DATE, REPORT_TYPE, REPORT_DATE_NAME
SECURITY_TYPE_CODE, NOTICE_DATE, UPDATE_DATE, CURRENCY, ACCEPT_DEPOSIT_INTERBANK, ACCOUNTS_PAYABLE, ACCOUNTS_RECE, ACCRUED_EXPENSE
ADVANCE_RECEIVABLES, AGENT_TRADE_SECURITY, AGENT_UNDERWRITE_SECURITY, AMORTIZE_COST_FINASSET, AMORTIZE_COST_FINLIAB, AMORTIZE_COST_NCFINASSET, AMORTIZE_COST_NCFINLIAB, APPOINT_FVTPL_FINASSET
APPOINT_FVTPL_FINLIAB, ASSET_BALANCE, ASSET_OTHER, ASSIGN_CASH_DIVIDEND, AVAILABLE_SALE_FINASSET, BOND_PAYABLE, BORROW_FUND, BUY_RESALE_FINASSET
CAPITAL_RESERVE, CIP, CONSUMPTIVE_BIOLOGICAL_ASSET, CONTRACT_ASSET, CONTRACT_LIAB, CONVERT_DIFF, CREDITOR_INVEST, CURRENT_ASSET_BALANCE
CURRENT_ASSET_OTHER, CURRENT_LIAB_BALANCE, CURRENT_LIAB_OTHER, DEFER_INCOME, DEFER_INCOME_1YEAR, DEFER_TAX_ASSET, DEFER_TAX_LIAB, DERIVE_FINASSET
DERIVE_FINLIAB, DEVELOP_EXPENSE, DIV_HOLDSALE_ASSET, DIV_HOLDSALE_LIAB, DIVIDEND_PAYABLE, DIVIDEND_RECE, EQUITY_BALANCE, EQUITY_OTHER
EXPORT_REFUND_RECE, FEE_COMMISSION_PAYABLE, FIN_FUND, FINANCE_RECE, FIXED_ASSET, FIXED_ASSET_DISPOSAL, FVTOCI_FINASSET, FVTOCI_NCFINASSET
FVTPL_FINASSET, FVTPL_FINLIAB, GENERAL_RISK_RESERVE, GOODWILL, HOLD_MATURITY_INVEST, HOLDSALE_ASSET, HOLDSALE_LIAB, INSURANCE_CONTRACT_RESERVE
INTANGIBLE_ASSET, INTEREST_PAYABLE, INTEREST_RECE, INTERNAL_PAYABLE, INTERNAL_RECE, INVENTORY, INVEST_REALESTATE, LEASE_LIAB
LEND_FUND, LIAB_BALANCE, LIAB_EQUITY_BALANCE, LIAB_EQUITY_OTHER, LIAB_OTHER, LOAN_ADVANCE, LOAN_PBC, LONG_EQUITY_INVEST
LONG_LOAN, LONG_PAYABLE, LONG_PREPAID_EXPENSE, LONG_RECE, LONG_STAFFSALARY_PAYABLE, MINORITY_EQUITY, MONETARYFUNDS, NONCURRENT_ASSET_1YEAR
NONCURRENT_ASSET_BALANCE, NONCURRENT_ASSET_OTHER, NONCURRENT_LIAB_1YEAR, NONCURRENT_LIAB_BALANCE, NONCURRENT_LIAB_OTHER, NOTE_ACCOUNTS_PAYABLE, NOTE_ACCOUNTS_RECE, NOTE_PAYABLE
NOTE_RECE, OIL_GAS_ASSET, OTHER_COMPRE_INCOME, OTHER_CREDITOR_INVEST, OTHER_CURRENT_ASSET, OTHER_CURRENT_LIAB, OTHER_EQUITY_INVEST, OTHER_EQUITY_OTHER
OTHER_EQUITY_TOOL, OTHER_NONCURRENT_ASSET, OTHER_NONCURRENT_FINASSET, OTHER_NONCURRENT_LIAB, OTHER_PAYABLE, OTHER_RECE, PARENT_EQUITY_BALANCE, PARENT_EQUITY_OTHER
PERPETUAL_BOND, PERPETUAL_BOND_PAYBALE, PREDICT_CURRENT_LIAB, PREDICT_LIAB, PREFERRED_SHARES, PREFERRED_SHARES_PAYBALE, PREMIUM_RECE, PREPAYMENT
PRODUCTIVE_BIOLOGY_ASSET, PROJECT_MATERIAL, RC_RESERVE_RECE, REINSURE_PAYABLE, REINSURE_RECE, SELL_REPO_FINASSET, SETTLE_EXCESS_RESERVE, SHARE_CAPITAL
SHORT_BOND_PAYABLE, SHORT_FIN_PAYABLE, SHORT_LOAN, SPECIAL_PAYABLE, SPECIAL_RESERVE, STAFF_SALARY_PAYABLE, SUBSIDY_RECE, SURPLUS_RESERVE
TAX_PAYABLE, TOTAL_ASSETS, TOTAL_CURRENT_ASSETS, TOTAL_CURRENT_LIAB, TOTAL_EQUITY, TOTAL_LIAB_EQUITY, TOTAL_LIABILITIES, TOTAL_NONCURRENT_ASSETS
TOTAL_NONCURRENT_LIAB, TOTAL_OTHER_PAYABLE, TOTAL_OTHER_RECE, TOTAL_PARENT_EQUITY, TRADE_FINASSET, TRADE_FINASSET_NOTFVTPL, TRADE_FINLIAB, TRADE_FINLIAB_NOTFVTPL
TREASURY_SHARES, UNASSIGN_RPOFIT, UNCONFIRM_INVEST_LOSS, USERIGHT_ASSET, ACCEPT_DEPOSIT_INTERBANK_YOY, ACCOUNTS_PAYABLE_YOY, ACCOUNTS_RECE_YOY, ACCRUED_EXPENSE_YOY
ADVANCE_RECEIVABLES_YOY, AGENT_TRADE_SECURITY_YOY, AGENT_UNDERWRITE_SECURITY_YOY, AMORTIZE_COST_FINASSET_YOY, AMORTIZE_COST_FINLIAB_YOY, AMORTIZE_COST_NCFINASSET_YOY, AMORTIZE_COST_NCFINLIAB_YOY, APPOINT_FVTPL_FINASSET_YOY
APPOINT_FVTPL_FINLIAB_YOY, ASSET_BALANCE_YOY, ASSET_OTHER_YOY, ASSIGN_CASH_DIVIDEND_YOY, AVAILABLE_SALE_FINASSET_YOY, BOND_PAYABLE_YOY, BORROW_FUND_YOY, BUY_RESALE_FINASSET_YOY
CAPITAL_RESERVE_YOY, CIP_YOY, CONSUMPTIVE_BIOLOGICAL_ASSET_YOY, CONTRACT_ASSET_YOY, CONTRACT_LIAB_YOY, CONVERT_DIFF_YOY, CREDITOR_INVEST_YOY, CURRENT_ASSET_BALANCE_YOY
CURRENT_ASSET_OTHER_YOY, CURRENT_LIAB_BALANCE_YOY, CURRENT_LIAB_OTHER_YOY, DEFER_INCOME_1YEAR_YOY, DEFER_INCOME_YOY, DEFER_TAX_ASSET_YOY, DEFER_TAX_LIAB_YOY, DERIVE_FINASSET_YOY
DERIVE_FINLIAB_YOY, DEVELOP_EXPENSE_YOY, DIV_HOLDSALE_ASSET_YOY, DIV_HOLDSALE_LIAB_YOY, DIVIDEND_PAYABLE_YOY, DIVIDEND_RECE_YOY, EQUITY_BALANCE_YOY, EQUITY_OTHER_YOY
EXPORT_REFUND_RECE_YOY, FEE_COMMISSION_PAYABLE_YOY, FIN_FUND_YOY, FINANCE_RECE_YOY, FIXED_ASSET_DISPOSAL_YOY, FIXED_ASSET_YOY, FVTOCI_FINASSET_YOY, FVTOCI_NCFINASSET_YOY
FVTPL_FINASSET_YOY, FVTPL_FINLIAB_YOY, GENERAL_RISK_RESERVE_YOY, GOODWILL_YOY, HOLD_MATURITY_INVEST_YOY, HOLDSALE_ASSET_YOY, HOLDSALE_LIAB_YOY, INSURANCE_CONTRACT_RESERVE_YOY
INTANGIBLE_ASSET_YOY, INTEREST_PAYABLE_YOY, INTEREST_RECE_YOY, INTERNAL_PAYABLE_YOY, INTERNAL_RECE_YOY, INVENTORY_YOY, INVEST_REALESTATE_YOY, LEASE_LIAB_YOY
LEND_FUND_YOY, LIAB_BALANCE_YOY, LIAB_EQUITY_BALANCE_YOY, LIAB_EQUITY_OTHER_YOY, LIAB_OTHER_YOY, LOAN_ADVANCE_YOY, LOAN_PBC_YOY, LONG_EQUITY_INVEST_YOY
LONG_LOAN_YOY, LONG_PAYABLE_YOY, LONG_PREPAID_EXPENSE_YOY, LONG_RECE_YOY, LONG_STAFFSALARY_PAYABLE_YOY, MINORITY_EQUITY_YOY, MONETARYFUNDS_YOY, NONCURRENT_ASSET_1YEAR_YOY
NONCURRENT_ASSET_BALANCE_YOY, NONCURRENT_ASSET_OTHER_YOY, NONCURRENT_LIAB_1YEAR_YOY, NONCURRENT_LIAB_BALANCE_YOY, NONCURRENT_LIAB_OTHER_YOY, NOTE_ACCOUNTS_PAYABLE_YOY, NOTE_ACCOUNTS_RECE_YOY, NOTE_PAYABLE_YOY
NOTE_RECE_YOY, OIL_GAS_ASSET_YOY, OTHER_COMPRE_INCOME_YOY, OTHER_CREDITOR_INVEST_YOY, OTHER_CURRENT_ASSET_YOY, OTHER_CURRENT_LIAB_YOY, OTHER_EQUITY_INVEST_YOY, OTHER_EQUITY_OTHER_YOY
OTHER_EQUITY_TOOL_YOY, OTHER_NONCURRENT_ASSET_YOY, OTHER_NONCURRENT_FINASSET_YOY, OTHER_NONCURRENT_LIAB_YOY, OTHER_PAYABLE_YOY, OTHER_RECE_YOY, PARENT_EQUITY_BALANCE_YOY, PARENT_EQUITY_OTHER_YOY
PERPETUAL_BOND_PAYBALE_YOY, PERPETUAL_BOND_YOY, PREDICT_CURRENT_LIAB_YOY, PREDICT_LIAB_YOY, PREFERRED_SHARES_PAYBALE_YOY, PREFERRED_SHARES_YOY, PREMIUM_RECE_YOY, PREPAYMENT_YOY
PRODUCTIVE_BIOLOGY_ASSET_YOY, PROJECT_MATERIAL_YOY, RC_RESERVE_RECE_YOY, REINSURE_PAYABLE_YOY, REINSURE_RECE_YOY, SELL_REPO_FINASSET_YOY, SETTLE_EXCESS_RESERVE_YOY, SHARE_CAPITAL_YOY
SHORT_BOND_PAYABLE_YOY, SHORT_FIN_PAYABLE_YOY, SHORT_LOAN_YOY, SPECIAL_PAYABLE_YOY, SPECIAL_RESERVE_YOY, STAFF_SALARY_PAYABLE_YOY, SUBSIDY_RECE_YOY, SURPLUS_RESERVE_YOY
TAX_PAYABLE_YOY, TOTAL_ASSETS_YOY, TOTAL_CURRENT_ASSETS_YOY, TOTAL_CURRENT_LIAB_YOY, TOTAL_EQUITY_YOY, TOTAL_LIAB_EQUITY_YOY, TOTAL_LIABILITIES_YOY, TOTAL_NONCURRENT_ASSETS_YOY
TOTAL_NONCURRENT_LIAB_YOY, TOTAL_OTHER_PAYABLE_YOY, TOTAL_OTHER_RECE_YOY, TOTAL_PARENT_EQUITY_YOY, TRADE_FINASSET_NOTFVTPL_YOY, TRADE_FINASSET_YOY, TRADE_FINLIAB_NOTFVTPL_YOY, TRADE_FINLIAB_YOY
TREASURY_SHARES_YOY, UNASSIGN_RPOFIT_YOY, UNCONFIRM_INVEST_LOSS_YOY, USERIGHT_ASSET_YOY, OPINION_TYPE, OSOPINION_TYPE, LISTING_STATE
```

- 样例（前 2 行）：

```json
[{"SECUCODE": "002773.SZ", "SECURITY_CODE": "002773", "SECURITY_NAME_ABBR": "康弘药业", "ORG_CODE": "10181907", "ORG_TYPE": "通用", "REPORT_DATE": "2026-09-30 00:00:00", "REPORT_TYPE": "三季报", "REPORT_DATE_NAME": "2026三季报", "SECURITY_TYPE_CODE": "058001001", "NOTICE_DATE": "2026-10-28 00:00:00", "UPDATE_DATE": "2026-10-28 00:00:00", "CURRENCY": "CNY", "ACCEPT_DEPOSIT_INTERBANK": null, "ACCOUNTS_PAYABLE": 159744739.04, "ACCOUNTS_RECE": 274390356.05, "ACCRUED_EXPENSE": null, "ADVANCE_RECEIVABLES": 52307.19, "AGENT_TRADE_SECURITY": null, "AGENT_UNDERWRITE_SECURITY": null, "AMORTIZE_COST_FINASSET": null, "AMORTIZE_COST_FINLIAB": null, "AMORTIZE_COST_NCFINASSET": null, "AMORTIZE_COST_NCFINLIAB": null, "APPOINT_FVTPL_FINASSET": null, "APPOINT_FVTPL_FINLIAB": null, "ASSET_BALANCE": 0.0, "ASSET_OTHER": null, "ASSIGN_CASH_DIVIDEND": null, "AVAILABLE_SALE_FINASSET": null, "BOND_PAYABLE": null, "BORROW_FUND": null, "BUY_RESALE_FINASSET": null, "CAPITAL_RESERVE": 2028428984.16, "CIP": 35331768.95, "CONSUMPTIVE_BIOLOGICAL_ASSET": null, "CONTRACT_ASSET": null, "CONTRACT_LIAB": 4498414.43, "CONVERT_DIFF": null, "CREDITOR_INVEST": null, "CURRENT_ASSET_BALANCE": 0.0, "CURRENT_ASSET_OTHER": null, "CURRENT_LIAB_BALANCE": 0.0, "CURRENT_LIAB_OTHER": null, "DEFER_INCOME": 28082521.29, "DEFER_INCOME_1YEAR": null, "DEFER_TAX_ASSET": 95070280.43, "DEFER_TAX_LIAB": 10546058.62, "DERIVE_FINASSET": null, "DERIVE_FINLIAB": null, "DEVELOP_EXPENSE": 189266527.41, "DIV_HOLDSALE_ASSET": null, "DIV_HOLDSALE_LIAB": n…（已截断）
```

### `stock_profit_sheet_by_report_em`

- 说明：东财利润表（SZ002773，按报告期）
- 参数：`symbol=SZ002773`
- 覆盖数据：财务三表与指标（含公告日）
- 更新频率：定期报告披露后
- 限流情况：按报告期批量抓取；建议 ≥0.5s/次
- 状态：可用
- 行数：55；耗时：7.8s
- 返回字段：

```text
SECUCODE, SECURITY_CODE, SECURITY_NAME_ABBR, ORG_CODE, ORG_TYPE, REPORT_DATE, REPORT_TYPE, REPORT_DATE_NAME
SECURITY_TYPE_CODE, NOTICE_DATE, UPDATE_DATE, CURRENCY, TOTAL_OPERATE_INCOME, TOTAL_OPERATE_INCOME_YOY, OPERATE_INCOME, OPERATE_INCOME_YOY
INTEREST_INCOME, INTEREST_INCOME_YOY, EARNED_PREMIUM, EARNED_PREMIUM_YOY, FEE_COMMISSION_INCOME, FEE_COMMISSION_INCOME_YOY, OTHER_BUSINESS_INCOME, OTHER_BUSINESS_INCOME_YOY
TOI_OTHER, TOI_OTHER_YOY, TOTAL_OPERATE_COST, TOTAL_OPERATE_COST_YOY, OPERATE_COST, OPERATE_COST_YOY, INTEREST_EXPENSE, INTEREST_EXPENSE_YOY
FEE_COMMISSION_EXPENSE, FEE_COMMISSION_EXPENSE_YOY, RESEARCH_EXPENSE, RESEARCH_EXPENSE_YOY, SURRENDER_VALUE, SURRENDER_VALUE_YOY, NET_COMPENSATE_EXPENSE, NET_COMPENSATE_EXPENSE_YOY
NET_CONTRACT_RESERVE, NET_CONTRACT_RESERVE_YOY, POLICY_BONUS_EXPENSE, POLICY_BONUS_EXPENSE_YOY, REINSURE_EXPENSE, REINSURE_EXPENSE_YOY, OTHER_BUSINESS_COST, OTHER_BUSINESS_COST_YOY
OPERATE_TAX_ADD, OPERATE_TAX_ADD_YOY, SALE_EXPENSE, SALE_EXPENSE_YOY, MANAGE_EXPENSE, MANAGE_EXPENSE_YOY, ME_RESEARCH_EXPENSE, ME_RESEARCH_EXPENSE_YOY
FINANCE_EXPENSE, FINANCE_EXPENSE_YOY, FE_INTEREST_EXPENSE, FE_INTEREST_EXPENSE_YOY, FE_INTEREST_INCOME, FE_INTEREST_INCOME_YOY, ASSET_IMPAIRMENT_LOSS, ASSET_IMPAIRMENT_LOSS_YOY
CREDIT_IMPAIRMENT_LOSS, CREDIT_IMPAIRMENT_LOSS_YOY, TOC_OTHER, TOC_OTHER_YOY, FAIRVALUE_CHANGE_INCOME, FAIRVALUE_CHANGE_INCOME_YOY, INVEST_INCOME, INVEST_INCOME_YOY
INVEST_JOINT_INCOME, INVEST_JOINT_INCOME_YOY, NET_EXPOSURE_INCOME, NET_EXPOSURE_INCOME_YOY, EXCHANGE_INCOME, EXCHANGE_INCOME_YOY, ASSET_DISPOSAL_INCOME, ASSET_DISPOSAL_INCOME_YOY
ASSET_IMPAIRMENT_INCOME, ASSET_IMPAIRMENT_INCOME_YOY, CREDIT_IMPAIRMENT_INCOME, CREDIT_IMPAIRMENT_INCOME_YOY, OTHER_INCOME, OTHER_INCOME_YOY, OPERATE_PROFIT_OTHER, OPERATE_PROFIT_OTHER_YOY
OPERATE_PROFIT_BALANCE, OPERATE_PROFIT_BALANCE_YOY, OPERATE_PROFIT, OPERATE_PROFIT_YOY, NONBUSINESS_INCOME, NONBUSINESS_INCOME_YOY, NONCURRENT_DISPOSAL_INCOME, NONCURRENT_DISPOSAL_INCOME_YOY
NONBUSINESS_EXPENSE, NONBUSINESS_EXPENSE_YOY, NONCURRENT_DISPOSAL_LOSS, NONCURRENT_DISPOSAL_LOSS_YOY, EFFECT_TP_OTHER, EFFECT_TP_OTHER_YOY, TOTAL_PROFIT_BALANCE, TOTAL_PROFIT_BALANCE_YOY
TOTAL_PROFIT, TOTAL_PROFIT_YOY, INCOME_TAX, INCOME_TAX_YOY, EFFECT_NETPROFIT_OTHER, EFFECT_NETPROFIT_OTHER_YOY, EFFECT_NETPROFIT_BALANCE, EFFECT_NETPROFIT_BALANCE_YOY
UNCONFIRM_INVEST_LOSS, UNCONFIRM_INVEST_LOSS_YOY, NETPROFIT, NETPROFIT_YOY, PRECOMBINE_PROFIT, PRECOMBINE_PROFIT_YOY, CONTINUED_NETPROFIT, CONTINUED_NETPROFIT_YOY
DISCONTINUED_NETPROFIT, DISCONTINUED_NETPROFIT_YOY, PARENT_NETPROFIT, PARENT_NETPROFIT_YOY, MINORITY_INTEREST, MINORITY_INTEREST_YOY, DEDUCT_PARENT_NETPROFIT, DEDUCT_PARENT_NETPROFIT_YOY
NETPROFIT_OTHER, NETPROFIT_OTHER_YOY, NETPROFIT_BALANCE, NETPROFIT_BALANCE_YOY, BASIC_EPS, BASIC_EPS_YOY, DILUTED_EPS, DILUTED_EPS_YOY
OTHER_COMPRE_INCOME, OTHER_COMPRE_INCOME_YOY, PARENT_OCI, PARENT_OCI_YOY, MINORITY_OCI, MINORITY_OCI_YOY, PARENT_OCI_OTHER, PARENT_OCI_OTHER_YOY
PARENT_OCI_BALANCE, PARENT_OCI_BALANCE_YOY, UNABLE_OCI, UNABLE_OCI_YOY, CREDITRISK_FAIRVALUE_CHANGE, CREDITRISK_FAIRVALUE_CHANGE_YOY, OTHERRIGHT_FAIRVALUE_CHANGE, OTHERRIGHT_FAIRVALUE_CHANGE_YOY
SETUP_PROFIT_CHANGE, SETUP_PROFIT_CHANGE_YOY, RIGHTLAW_UNABLE_OCI, RIGHTLAW_UNABLE_OCI_YOY, UNABLE_OCI_OTHER, UNABLE_OCI_OTHER_YOY, UNABLE_OCI_BALANCE, UNABLE_OCI_BALANCE_YOY
ABLE_OCI, ABLE_OCI_YOY, RIGHTLAW_ABLE_OCI, RIGHTLAW_ABLE_OCI_YOY, AFA_FAIRVALUE_CHANGE, AFA_FAIRVALUE_CHANGE_YOY, HMI_AFA, HMI_AFA_YOY
CASHFLOW_HEDGE_VALID, CASHFLOW_HEDGE_VALID_YOY, CREDITOR_FAIRVALUE_CHANGE, CREDITOR_FAIRVALUE_CHANGE_YOY, CREDITOR_IMPAIRMENT_RESERVE, CREDITOR_IMPAIRMENT_RESERVE_YOY, FINANCE_OCI_AMT, FINANCE_OCI_AMT_YOY
CONVERT_DIFF, CONVERT_DIFF_YOY, ABLE_OCI_OTHER, ABLE_OCI_OTHER_YOY, ABLE_OCI_BALANCE, ABLE_OCI_BALANCE_YOY, OCI_OTHER, OCI_OTHER_YOY
OCI_BALANCE, OCI_BALANCE_YOY, TOTAL_COMPRE_INCOME, TOTAL_COMPRE_INCOME_YOY, PARENT_TCI, PARENT_TCI_YOY, MINORITY_TCI, MINORITY_TCI_YOY
PRECOMBINE_TCI, PRECOMBINE_TCI_YOY, EFFECT_TCI_BALANCE, EFFECT_TCI_BALANCE_YOY, TCI_OTHER, TCI_OTHER_YOY, TCI_BALANCE, TCI_BALANCE_YOY
ACF_END_INCOME, ACF_END_INCOME_YOY, OPINION_TYPE
```

- 样例（前 2 行）：

```json
[{"SECUCODE": "002773.SZ", "SECURITY_CODE": "002773", "SECURITY_NAME_ABBR": "康弘药业", "ORG_CODE": "10181907", "ORG_TYPE": "通用", "REPORT_DATE": "2026-09-30 00:00:00", "REPORT_TYPE": "三季报", "REPORT_DATE_NAME": "2026三季报", "SECURITY_TYPE_CODE": "058001001", "NOTICE_DATE": "2026-10-28 00:00:00", "UPDATE_DATE": "2026-10-28 00:00:00", "CURRENCY": "CNY", "TOTAL_OPERATE_INCOME": 3171579261.56, "TOTAL_OPERATE_INCOME_YOY": -12.4807731388, "OPERATE_INCOME": 3171579261.56, "OPERATE_INCOME_YOY": -12.4807731388, "INTEREST_INCOME": null, "INTEREST_INCOME_YOY": null, "EARNED_PREMIUM": null, "EARNED_PREMIUM_YOY": null, "FEE_COMMISSION_INCOME": null, "FEE_COMMISSION_INCOME_YOY": null, "OTHER_BUSINESS_INCOME": null, "OTHER_BUSINESS_INCOME_YOY": null, "TOI_OTHER": null, "TOI_OTHER_YOY": null, "TOTAL_OPERATE_COST": 2243327871.73, "TOTAL_OPERATE_COST_YOY": -8.0054299781, "OPERATE_COST": 359006480.58, "OPERATE_COST_YOY": 2.4334278038, "INTEREST_EXPENSE": null, "INTEREST_EXPENSE_YOY": null, "FEE_COMMISSION_EXPENSE": null, "FEE_COMMISSION_EXPENSE_YOY": null, "RESEARCH_EXPENSE": 353898333.5, "RESEARCH_EXPENSE_YOY": 5.9076243188, "SURRENDER_VALUE": null, "SURRENDER_VALUE_YOY": null, "NET_COMPENSATE_EXPENSE": null, "NET_COMPENSATE_EXPENSE_YOY": null, "NET_CONTRACT_RESERVE": null, "NET_CONTRACT_RESERVE_YOY": null, "POLICY_BONUS_EXPENSE": null, "POLICY_BONUS_EXPENSE_YOY": null, "REINSURE_EXPENSE": null, "REINSURE_EXPENSE_YOY": null, "OTHER_BUSINESS_COST": null, "OTHER_BUSINESS_COST_YOY": null, "OPERATE_TAX_A…（已截断）
```

### `stock_cash_flow_sheet_by_report_em`

- 说明：东财现金流量表（SZ002773，按报告期）
- 参数：`symbol=SZ002773`
- 覆盖数据：财务三表与指标（含公告日）
- 更新频率：定期报告披露后
- 限流情况：按报告期批量抓取；建议 ≥0.5s/次
- 状态：可用
- 行数：55；耗时：9.03s
- 返回字段：

```text
SECUCODE, SECURITY_CODE, SECURITY_NAME_ABBR, ORG_CODE, ORG_TYPE, REPORT_DATE, REPORT_TYPE, REPORT_DATE_NAME
SECURITY_TYPE_CODE, NOTICE_DATE, UPDATE_DATE, CURRENCY, SALES_SERVICES, DEPOSIT_INTERBANK_ADD, LOAN_PBC_ADD, OFI_BF_ADD
RECEIVE_ORIGIC_PREMIUM, RECEIVE_REINSURE_NET, INSURED_INVEST_ADD, DISPOSAL_TFA_ADD, RECEIVE_INTEREST_COMMISSION, BORROW_FUND_ADD, LOAN_ADVANCE_REDUCE, REPO_BUSINESS_ADD
RECEIVE_TAX_REFUND, RECEIVE_OTHER_OPERATE, OPERATE_INFLOW_OTHER, OPERATE_INFLOW_BALANCE, TOTAL_OPERATE_INFLOW, BUY_SERVICES, LOAN_ADVANCE_ADD, PBC_INTERBANK_ADD
PAY_ORIGIC_COMPENSATE, PAY_INTEREST_COMMISSION, PAY_POLICY_BONUS, PAY_STAFF_CASH, PAY_ALL_TAX, PAY_OTHER_OPERATE, OPERATE_OUTFLOW_OTHER, OPERATE_OUTFLOW_BALANCE
TOTAL_OPERATE_OUTFLOW, OPERATE_NETCASH_OTHER, OPERATE_NETCASH_BALANCE, NETCASH_OPERATE, WITHDRAW_INVEST, RECEIVE_INVEST_INCOME, DISPOSAL_LONG_ASSET, DISPOSAL_SUBSIDIARY_OTHER
REDUCE_PLEDGE_TIMEDEPOSITS, RECEIVE_OTHER_INVEST, INVEST_INFLOW_OTHER, INVEST_INFLOW_BALANCE, TOTAL_INVEST_INFLOW, CONSTRUCT_LONG_ASSET, INVEST_PAY_CASH, PLEDGE_LOAN_ADD
OBTAIN_SUBSIDIARY_OTHER, ADD_PLEDGE_TIMEDEPOSITS, PAY_OTHER_INVEST, INVEST_OUTFLOW_OTHER, INVEST_OUTFLOW_BALANCE, TOTAL_INVEST_OUTFLOW, INVEST_NETCASH_OTHER, INVEST_NETCASH_BALANCE
NETCASH_INVEST, ACCEPT_INVEST_CASH, SUBSIDIARY_ACCEPT_INVEST, RECEIVE_LOAN_CASH, ISSUE_BOND, RECEIVE_OTHER_FINANCE, FINANCE_INFLOW_OTHER, FINANCE_INFLOW_BALANCE
TOTAL_FINANCE_INFLOW, PAY_DEBT_CASH, ASSIGN_DIVIDEND_PORFIT, SUBSIDIARY_PAY_DIVIDEND, BUY_SUBSIDIARY_EQUITY, PAY_OTHER_FINANCE, SUBSIDIARY_REDUCE_CASH, FINANCE_OUTFLOW_OTHER
FINANCE_OUTFLOW_BALANCE, TOTAL_FINANCE_OUTFLOW, FINANCE_NETCASH_OTHER, FINANCE_NETCASH_BALANCE, NETCASH_FINANCE, RATE_CHANGE_EFFECT, CCE_ADD_OTHER, CCE_ADD_BALANCE
CCE_ADD, BEGIN_CCE, END_CCE_OTHER, END_CCE_BALANCE, END_CCE, NETPROFIT, ASSET_IMPAIRMENT, FA_IR_DEPR
OILGAS_BIOLOGY_DEPR, IR_DEPR, IA_AMORTIZE, LPE_AMORTIZE, DEFER_INCOME_AMORTIZE, PREPAID_EXPENSE_REDUCE, ACCRUED_EXPENSE_ADD, DISPOSAL_LONGASSET_LOSS
FA_SCRAP_LOSS, FAIRVALUE_CHANGE_LOSS, FINANCE_EXPENSE, INVEST_LOSS, DEFER_TAX, DT_ASSET_REDUCE, DT_LIAB_ADD, PREDICT_LIAB_ADD
INVENTORY_REDUCE, OPERATE_RECE_REDUCE, OPERATE_PAYABLE_ADD, OTHER, OPERATE_NETCASH_OTHERNOTE, OPERATE_NETCASH_BALANCENOTE, NETCASH_OPERATENOTE, DEBT_TRANSFER_CAPITAL
CONVERT_BOND_1YEAR, FINLEASE_OBTAIN_FA, UNINVOLVE_INVESTFIN_OTHER, END_CASH, BEGIN_CASH, END_CASH_EQUIVALENTS, BEGIN_CASH_EQUIVALENTS, CCE_ADD_OTHERNOTE
CCE_ADD_BALANCENOTE, CCE_ADDNOTE, SALES_SERVICES_YOY, DEPOSIT_INTERBANK_ADD_YOY, LOAN_PBC_ADD_YOY, OFI_BF_ADD_YOY, RECEIVE_ORIGIC_PREMIUM_YOY, RECEIVE_REINSURE_NET_YOY
INSURED_INVEST_ADD_YOY, DISPOSAL_TFA_ADD_YOY, RECEIVE_INTEREST_COMMISSION_YOY, BORROW_FUND_ADD_YOY, LOAN_ADVANCE_REDUCE_YOY, REPO_BUSINESS_ADD_YOY, RECEIVE_TAX_REFUND_YOY, RECEIVE_OTHER_OPERATE_YOY
OPERATE_INFLOW_OTHER_YOY, OPERATE_INFLOW_BALANCE_YOY, TOTAL_OPERATE_INFLOW_YOY, BUY_SERVICES_YOY, LOAN_ADVANCE_ADD_YOY, PBC_INTERBANK_ADD_YOY, PAY_ORIGIC_COMPENSATE_YOY, PAY_INTEREST_COMMISSION_YOY
PAY_POLICY_BONUS_YOY, PAY_STAFF_CASH_YOY, PAY_ALL_TAX_YOY, PAY_OTHER_OPERATE_YOY, OPERATE_OUTFLOW_OTHER_YOY, OPERATE_OUTFLOW_BALANCE_YOY, TOTAL_OPERATE_OUTFLOW_YOY, OPERATE_NETCASH_OTHER_YOY
OPERATE_NETCASH_BALANCE_YOY, NETCASH_OPERATE_YOY, WITHDRAW_INVEST_YOY, RECEIVE_INVEST_INCOME_YOY, DISPOSAL_LONG_ASSET_YOY, DISPOSAL_SUBSIDIARY_OTHER_YOY, REDUCE_PLEDGE_TIMEDEPOSITS_YOY, RECEIVE_OTHER_INVEST_YOY
INVEST_INFLOW_OTHER_YOY, INVEST_INFLOW_BALANCE_YOY, TOTAL_INVEST_INFLOW_YOY, CONSTRUCT_LONG_ASSET_YOY, INVEST_PAY_CASH_YOY, PLEDGE_LOAN_ADD_YOY, OBTAIN_SUBSIDIARY_OTHER_YOY, ADD_PLEDGE_TIMEDEPOSITS_YOY
PAY_OTHER_INVEST_YOY, INVEST_OUTFLOW_OTHER_YOY, INVEST_OUTFLOW_BALANCE_YOY, TOTAL_INVEST_OUTFLOW_YOY, INVEST_NETCASH_OTHER_YOY, INVEST_NETCASH_BALANCE_YOY, NETCASH_INVEST_YOY, ACCEPT_INVEST_CASH_YOY
SUBSIDIARY_ACCEPT_INVEST_YOY, RECEIVE_LOAN_CASH_YOY, ISSUE_BOND_YOY, RECEIVE_OTHER_FINANCE_YOY, FINANCE_INFLOW_OTHER_YOY, FINANCE_INFLOW_BALANCE_YOY, TOTAL_FINANCE_INFLOW_YOY, PAY_DEBT_CASH_YOY
ASSIGN_DIVIDEND_PORFIT_YOY, SUBSIDIARY_PAY_DIVIDEND_YOY, BUY_SUBSIDIARY_EQUITY_YOY, PAY_OTHER_FINANCE_YOY, SUBSIDIARY_REDUCE_CASH_YOY, FINANCE_OUTFLOW_OTHER_YOY, FINANCE_OUTFLOW_BALANCE_YOY, TOTAL_FINANCE_OUTFLOW_YOY
FINANCE_NETCASH_OTHER_YOY, FINANCE_NETCASH_BALANCE_YOY, NETCASH_FINANCE_YOY, RATE_CHANGE_EFFECT_YOY, CCE_ADD_OTHER_YOY, CCE_ADD_BALANCE_YOY, CCE_ADD_YOY, BEGIN_CCE_YOY
END_CCE_OTHER_YOY, END_CCE_BALANCE_YOY, END_CCE_YOY, NETPROFIT_YOY, ASSET_IMPAIRMENT_YOY, FA_IR_DEPR_YOY, OILGAS_BIOLOGY_DEPR_YOY, IR_DEPR_YOY
IA_AMORTIZE_YOY, LPE_AMORTIZE_YOY, DEFER_INCOME_AMORTIZE_YOY, PREPAID_EXPENSE_REDUCE_YOY, ACCRUED_EXPENSE_ADD_YOY, DISPOSAL_LONGASSET_LOSS_YOY, FA_SCRAP_LOSS_YOY, FAIRVALUE_CHANGE_LOSS_YOY
FINANCE_EXPENSE_YOY, INVEST_LOSS_YOY, DEFER_TAX_YOY, DT_ASSET_REDUCE_YOY, DT_LIAB_ADD_YOY, PREDICT_LIAB_ADD_YOY, INVENTORY_REDUCE_YOY, OPERATE_RECE_REDUCE_YOY
OPERATE_PAYABLE_ADD_YOY, OTHER_YOY, OPERATE_NETCASH_OTHERNOTE_YOY, OPERATE_NETCASH_BALANCENOTE_YOY, NETCASH_OPERATENOTE_YOY, DEBT_TRANSFER_CAPITAL_YOY, CONVERT_BOND_1YEAR_YOY, FINLEASE_OBTAIN_FA_YOY
UNINVOLVE_INVESTFIN_OTHER_YOY, END_CASH_YOY, BEGIN_CASH_YOY, END_CASH_EQUIVALENTS_YOY, BEGIN_CASH_EQUIVALENTS_YOY, CCE_ADD_OTHERNOTE_YOY, CCE_ADD_BALANCENOTE_YOY, CCE_ADDNOTE_YOY
OPINION_TYPE, OSOPINION_TYPE, MINORITY_INTEREST, MINORITY_INTEREST_YOY, USERIGHT_ASSET_AMORTIZE, USERIGHT_ASSET_AMORTIZE_YOY
```

- 样例（前 2 行）：

```json
[{"SECUCODE": "002773.SZ", "SECURITY_CODE": "002773", "SECURITY_NAME_ABBR": "康弘药业", "ORG_CODE": "10181907", "ORG_TYPE": "通用", "REPORT_DATE": "2026-09-30 00:00:00", "REPORT_TYPE": "三季报", "REPORT_DATE_NAME": "2026三季报", "SECURITY_TYPE_CODE": "058001001", "NOTICE_DATE": "2026-10-28 00:00:00", "UPDATE_DATE": "2026-10-28 00:00:00", "CURRENCY": "CNY", "SALES_SERVICES": 3384546075.62, "DEPOSIT_INTERBANK_ADD": null, "LOAN_PBC_ADD": null, "OFI_BF_ADD": null, "RECEIVE_ORIGIC_PREMIUM": null, "RECEIVE_REINSURE_NET": null, "INSURED_INVEST_ADD": null, "DISPOSAL_TFA_ADD": null, "RECEIVE_INTEREST_COMMISSION": null, "BORROW_FUND_ADD": null, "LOAN_ADVANCE_REDUCE": null, "REPO_BUSINESS_ADD": null, "RECEIVE_TAX_REFUND": 526464.44, "RECEIVE_OTHER_OPERATE": 61985861.98, "OPERATE_INFLOW_OTHER": null, "OPERATE_INFLOW_BALANCE": 0.0, "TOTAL_OPERATE_INFLOW": 3447058402.04, "BUY_SERVICES": 263692905.9, "LOAN_ADVANCE_ADD": null, "PBC_INTERBANK_ADD": null, "PAY_ORIGIC_COMPENSATE": null, "PAY_INTEREST_COMMISSION": null, "PAY_POLICY_BONUS": null, "PAY_STAFF_CASH": 938828311.83, "PAY_ALL_TAX": 497530219.87, "PAY_OTHER_OPERATE": 935134339.41, "OPERATE_OUTFLOW_OTHER": null, "OPERATE_OUTFLOW_BALANCE": 0.0, "TOTAL_OPERATE_OUTFLOW": 2635185777.01, "OPERATE_NETCASH_OTHER": null, "OPERATE_NETCASH_BALANCE": 0.0, "NETCASH_OPERATE": 811872625.03, "WITHDRAW_INVEST": 1555000000.0, "RECEIVE_INVEST_INCOME": 4553202.23, "DISPOSAL_LONG_ASSET": 82069.61, "DISPOSAL_SUBSIDIARY_OTHER": null, "REDUCE_PLEDGE_TIMEDEPOSITS": null, "…（已截断）
```

### `stock_financial_report_sina_cashflow`

- 说明：新浪现金流量表（sz002773）
- 参数：`stock=sz002773`, `symbol=现金流量表`
- 覆盖数据：财务三表与指标（含公告日）
- 更新频率：定期报告披露后
- 限流情况：按报告期批量抓取；建议 ≥0.5s/次
- 状态：可用
- 行数：55；耗时：3.3s
- 返回字段：

```text
报告日, 经营活动产生的现金流量, 销售商品、提供劳务收到的现金, 客户存款和同业存放款项净增加额, 向中央银行借款净增加额, 向其他金融机构拆入资金净增加额, 收到原保险合同保费取得的现金, 收到再保险业务现金净额
保户储金及投资款净增加额, 处置交易性金融资产净增加额, 收取利息、手续费及佣金的现金, 拆入资金净增加额, 回购业务资金净增加额, 收到的税费返还, 收到的其他与经营活动有关的现金, 经营活动现金流入小计
购买商品、接受劳务支付的现金, 客户贷款及垫款净增加额, 存放中央银行和同业款项净增加额, 支付原保险合同赔付款项的现金, 支付利息、手续费及佣金的现金, 支付保单红利的现金, 支付给职工以及为职工支付的现金, 支付的各项税费
支付的其他与经营活动有关的现金, 经营活动现金流出小计, 经营活动产生的现金流量净额, 投资活动产生的现金流量, 收回投资所收到的现金, 取得投资收益收到的现金, 处置固定资产、无形资产和其他长期资产所收回的现金净额, 处置子公司及其他营业单位收到的现金净额
收到的其他与投资活动有关的现金, 减少质押和定期存款所收到的现金, 处置可供出售金融资产净增加额, 投资活动现金流入小计, 购建固定资产、无形资产和其他长期资产所支付的现金, 投资所支付的现金, 质押贷款净增加额, 取得子公司及其他营业单位支付的现金净额
增加质押和定期存款所支付的现金, 支付的其他与投资活动有关的现金, 投资活动现金流出小计, 投资活动产生的现金流量净额, 筹资活动产生的现金流量, 吸收投资收到的现金, 子公司吸收少数股东投资收到的现金, 取得借款收到的现金
发行债券收到的现金, 收到其他与筹资活动有关的现金, 筹资活动现金流入小计, 偿还债务支付的现金, 分配股利、利润或偿付利息所支付的现金, 子公司支付给少数股东的股利、利润, 支付其他与筹资活动有关的现金, 筹资活动现金流出小计
筹资活动产生的现金流量净额, 汇率变动对现金及现金等价物的影响, 现金及现金等价物净增加额, 期初现金及现金等价物余额, 现金的期末余额, 现金的期初余额, 现金等价物的期末余额, 现金等价物的期初余额
期末现金及现金等价物余额, 数据源, 是否审计, 公告日期, 币种, 类型, 更新日期
```

- 样例（前 2 行）：

```json
[{"报告日": "20260930", "经营活动产生的现金流量": null, "销售商品、提供劳务收到的现金": 3384546075.62, "客户存款和同业存放款项净增加额": null, "向中央银行借款净增加额": null, "向其他金融机构拆入资金净增加额": null, "收到原保险合同保费取得的现金": null, "收到再保险业务现金净额": null, "保户储金及投资款净增加额": null, "处置交易性金融资产净增加额": null, "收取利息、手续费及佣金的现金": null, "拆入资金净增加额": null, "回购业务资金净增加额": null, "收到的税费返还": 526464.44, "收到的其他与经营活动有关的现金": 61985861.98, "经营活动现金流入小计": 3447058402.04, "购买商品、接受劳务支付的现金": 263692905.9, "客户贷款及垫款净增加额": null, "存放中央银行和同业款项净增加额": null, "支付原保险合同赔付款项的现金": null, "支付利息、手续费及佣金的现金": null, "支付保单红利的现金": null, "支付给职工以及为职工支付的现金": 938828311.83, "支付的各项税费": 497530219.87, "支付的其他与经营活动有关的现金": 935134339.41, "经营活动现金流出小计": 2635185777.01, "经营活动产生的现金流量净额": 811872625.03, "投资活动产生的现金流量": null, "收回投资所收到的现金": 1555000000.0, "取得投资收益收到的现金": 4553202.23, "处置固定资产、无形资产和其他长期资产所收回的现金净额": 82069.61, "处置子公司及其他营业单位收到的现金净额": null, "收到的其他与投资活动有关的现金": 690000.0, "减少质押和定期存款所收到的现金": null, "处置可供出售金融资产净增加额": null, "投资活动现金流入小计": 1560325271.84, "购建固定资产、无形资产和其他长期资产所支付的现金": 225631603.41, "投资所支付的现金": 4524000000.0, "质押贷款净增加额": null, "取得子公司及其他营业单位支付的现金净额": null, "增加质押和定期存款所支付的现金": null, "支付的其他与投资活动有关的现金": 1400635.17, "投资活动现金流出小计": 4751032238.58, "投资活动产生的现金流量净额": -3190706966.74, "筹资活动产生的现金流量": null, "吸收投资收到的现金": 74736.0, "子公司吸收少数股东投资收到的现金": null, "取得借款收到的现金": null, "发行债券收到的现金": null, "收到其他与筹资活动有关的现金": null, "筹资活动现金流入小计": 74736.0, "偿还债务支付的现金": null, "分配股利、利润或偿付利息所支付的现金": 644928447.8, "子公司支付给少数股东的股利、利润": null, "支付其他与筹资活动有关的现金": 1788572.03, "筹资活动现金流出小计": 646717019.83, "筹资活动产生的现金流量净额": -646642283.83, "汇率变动对现金及现金等价物的…（已截断）
```

### `stock_financial_report_sina_balance`

- 说明：新浪资产负债表（sz002773）
- 参数：`stock=sz002773`, `symbol=资产负债表`
- 覆盖数据：财务三表与指标（含公告日）
- 更新频率：定期报告披露后
- 限流情况：按报告期批量抓取；建议 ≥0.5s/次
- 状态：可用
- 行数：52；耗时：3.82s
- 返回字段：

```text
报告日, 流动资产, 货币资金, 结算备付金, 拆出资金, 交易性金融资产, 买入返售金融资产, 衍生金融资产
应收票据及应收账款, 应收票据, 应收账款, 应收款项融资, 预付款项, 应收股利, 应收利息, 应收保费
应收分保账款, 应收分保合同准备金, 应收出口退税, 应收补贴款, 应收保证金, 内部应收款, 其他应收款, 其他应收款(合计)
存货, 划分为持有待售的资产, 待摊费用, 待处理流动资产损益, 一年内到期的非流动资产, 其他流动资产, 流动资产合计, 非流动资产
发放贷款及垫款, 债权投资, 其他债权投资, 以公允价值计量且其变动计入其他综合收益的金融资产, 以摊余成本计量的金融资产, 可供出售金融资产, 长期股权投资, 投资性房地产
长期应收款, 其他权益工具投资, 其他非流动金融资产, 其他长期投资, 固定资产原值, 累计折旧, 固定资产净值, 固定资产减值准备
在建工程合计, 在建工程, 工程物资, 固定资产净额, 固定资产清理, 固定资产及清理合计, 生产性生物资产, 公益性生物资产
油气资产, 合同资产, 使用权资产, 无形资产, 开发支出, 商誉, 长期待摊费用, 股权分置流通权
递延所得税资产, 其他非流动资产, 非流动资产合计, 资产总计, 流动负债, 短期借款, 向中央银行借款, 吸收存款及同业存放
拆入资金, 交易性金融负债, 衍生金融负债, 应付票据及应付账款, 应付票据, 应付账款, 预收款项, 合同负债
卖出回购金融资产款, 应付手续费及佣金, 应付职工薪酬, 应交税费, 应付利息, 应付股利, 应付保证金, 内部应付款
其他应付款, 其他应付款合计, 其他应交款, 担保责任赔偿准备金, 应付分保账款, 保险合同准备金, 代理买卖证券款, 代理承销证券款
国际票证结算, 国内票证结算, 预提费用, 预计流动负债, 应付短期债券, 划分为持有待售的负债, 一年内的递延收益, 一年内到期的非流动负债
其他流动负债, 流动负债合计, 非流动负债, 长期借款, 应付债券, 应付债券：优先股, 应付债券：永续债, 租赁负债
长期应付职工薪酬, 长期应付款, 长期应付款合计, 专项应付款, 预计非流动负债, 长期递延收益, 递延所得税负债, 其他非流动负债
非流动负债合计, 负债合计, 所有者权益, 实收资本(或股本), 其他权益工具, 优先股, 永续债, 资本公积
减:库存股, 其他综合收益, 专项储备, 盈余公积, 一般风险准备, 未确定的投资损失, 未分配利润, 拟分配现金股利
外币报表折算差额, 归属于母公司股东权益合计, 少数股东权益, 所有者权益(或股东权益)合计, 负债和所有者权益(或股东权益)总计, 数据源, 是否审计, 公告日期
币种, 类型, 更新日期
```

- 样例（前 2 行）：

```json
[{"报告日": "20260930", "流动资产": null, "货币资金": 3425314458.64, "结算备付金": null, "拆出资金": null, "交易性金融资产": 2969000000.0, "买入返售金融资产": null, "衍生金融资产": null, "应收票据及应收账款": 275401556.05, "应收票据": 1011200.0, "应收账款": 274390356.05, "应收款项融资": null, "预付款项": 89079003.34, "应收股利": null, "应收利息": null, "应收保费": null, "应收分保账款": null, "应收分保合同准备金": null, "应收出口退税": null, "应收补贴款": null, "应收保证金": null, "内部应收款": null, "其他应收款": null, "其他应收款(合计)": 10123584.11, "存货": 413186363.14, "划分为持有待售的资产": null, "待摊费用": null, "待处理流动资产损益": null, "一年内到期的非流动资产": null, "其他流动资产": 52680594.69, "流动资产合计": 7234785559.97, "非流动资产": null, "发放贷款及垫款": null, "债权投资": null, "其他债权投资": null, "以公允价值计量且其变动计入其他综合收益的金融资产": null, "以摊余成本计量的金融资产": null, "可供出售金融资产": null, "长期股权投资": 15282408.79, "投资性房地产": null, "长期应收款": null, "其他权益工具投资": null, "其他非流动金融资产": null, "其他长期投资": null, "固定资产原值": null, "累计折旧": null, "固定资产净值": null, "固定资产减值准备": null, "在建工程合计": 35331768.95, "在建工程": null, "工程物资": null, "固定资产净额": null, "固定资产清理": null, "固定资产及清理合计": 2100644158.11, "生产性生物资产": 2015609.96, "公益性生物资产": null, "油气资产": null, "合同资产": null, "使用权资产": 1587974.38, "无形资产": 333378627.23, "开发支出": 189266527.41, "商誉": null, "长期待摊费用": 797410.01, "股权分置流通权": null, "递延所得税资产": 95070280.43, "其他非流动资产": 49408606.63, "非流动资产合计": 2822783371.9, "资产总计": 10057568931.87, "流动负债": null, "短期借款": null, "向中央银行借款": null, "吸收存款及同业存放": null, "拆入资金": null, "交易性金融负债": null, "衍生金融负债": null, "应付票据及应付账款": 159744739.04, "应付票据": null, "应付账款": 159744739.04, "预收款项": 52307.19, "合同负债": 4498414.43, "卖出回购金融资产款": null,…（已截断）
```

## 结论与注意事项

- 当前环境为 Windows，系统代理会拦截部分行情站点。东财 `push2his` 系列
  （`stock_zh_a_hist`、`index_zh_a_hist`、`stock_zh_index_daily_em`）在本机不可达；
  日线主源改用新浪 `stock_zh_a_daily` 或腾讯 `stock_zh_a_hist_tx`，指数使用新浪
  `stock_zh_index_daily` 或申万 `index_hist_sw`。
- 申万行业相关接口需要系统证书信任；探测时对相关接口设置 `NO_PROXY=*` 并注入
  `truststore`（仅探测脚本使用，正式采集需在部署环境确认证书与代理策略）。
- `stock_industry_clf_hist_sw` 返回申万历史分类的 `industry_code`（如 `440101`），
  需结合 `sw_index_first_info` / `sw_index_second_info` / `sw_index_third_cons`
  建立代码到一级/二级名称的映射；映射规则在 T0.4 实现并用 7 只校准股核对。
- 公告列表可用东财 `stock_notice_report` / `stock_individual_notice_report`（返回标题、
  分类、日期、详情页 URL）。巨潮 `stock_zh_a_disclosure_report_cninfo` 在本环境多次
  被限流（返回非 JSON），它是正文 PDF 的主要入口，正式采集必须做指数退避重试并缓存。
  正文 PDF 下载后再用 pdfplumber 解析；扫描件按配置 `ingest.skip_scanned_pdf` 跳过。
- 一致预期以商业源为主。东财/同花顺开源接口仅作探测与临时校验，字段含义和稳定性
  不满足 PIT 要求，不写入正式一致预期表。
- 估值首选东财 `stock_value_em`：一次返回全部历史，含 PE(TTM)/PE(静)/市净率/市销率/总市值；
  百度接口仅作 PE/PB 备用（该接口不提供市销率）。
- 东财财务指标接口 `stock_financial_analysis_indicator_em` 的 `symbol` 必须带市场后缀
  （如 `002773.SZ`），否则接口返回空结果。返回字段含 `NOTICE_DATE`、`ROEJQ`、`ROIC`、
  `ZCFZL`、`INTEREST_DEBT_RATIO`，可直接用于 PIT 与财务健康度计算。
- 机构调研按个股过滤的原始接口（`em_research_visits_by_stock`）可用；AKShare 的
  `stock_jgdy_detail_em` 会从起始日全量分页，单日数百页，正式采集不要使用。
- 所有采集函数必须支持断点续传、指数退避重试；请求间隔等参数在 T0.4 写入
  `config/settings.yaml` 的 `ingest` 分组，不在代码中硬编码。
