# 服务接口

`GET /api/plan?capacity=15` 返回默认快照下的完整方案。`POST /api/plan` 支持提交本地记录，`packet` 内仅含 `observations` 和 `outcomes` 列表。

`GET /api/summary` 返回简读版。`GET /api/decisions/<case_id>` 回读对应测量与标准化特征。`GET /api/compare?capacity=15&against=0` 显示两档额度的逐单状态变更。

以下模块证据可通过 `/api/modules/` 下的相同名称访问。

- `lighting_holds`
- `booking_signals`
- `rental_hist_bayes`
- `shoot_holdout`
- `client_mix`
- `gear_reuse`

`GET /api/decisions.csv` 导出本次候选。`POST /api/releases` 接受规划请求的原参数及 `expected_generation`、`run_id`。重试同一个运行标识返回原版本，试图用过期版本登记其他方案返回 409。
