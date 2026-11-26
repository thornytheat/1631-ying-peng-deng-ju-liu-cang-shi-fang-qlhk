# 模块与边界验证

所属领域 AI/ML，子方向 传统ML。

## 功能模块

| 序号 | 模块 | 职责 | 实现 | 测试 |
| --- | --- | --- | --- | --- |
| M1 | lighting_holds | 单据接入与时点裁决 | `src/lightbooking/lighting_holds/service.py` | `tests/test_lighting_holds.py` |
| M2 | booking_signals | 业务特征与时点档案 | `src/lightbooking/booking_signals/service.py` | `tests/test_booking_signals.py` |
| M3 | rental_hist_bayes | 训练、估计与基线 | `src/lightbooking/rental_hist_bayes/service.py` | `tests/test_rental_hist_bayes.py` |
| M4 | shoot_holdout | 时间回放与核验 | `src/lightbooking/shoot_holdout/service.py` | `tests/test_shoot_holdout.py` |
| M5 | client_mix | 群组偏移与可信分派 | `src/lightbooking/client_mix/service.py` | `tests/test_client_mix.py` |
| M6 | gear_reuse | 业务锁与资源分派 | `src/lightbooking/gear_reuse/service.py` | `tests/test_gear_reuse.py` |
| M7 | checkout_reconcile | 逐单证据与资源守恒 | `src/lightbooking/checkout_reconcile/service.py` | `tests/test_checkout_reconcile.py` |
| M8 | hold_registry | 版本登记与追溯 | `src/lightbooking/hold_registry/service.py` | `tests/test_hold_registry.py` |

## 易错边界

| 用例 | 业务后果 | 处理位置 | 验证位置 |
| --- | --- | --- | --- |
| TRAP-14 | 同版本异值隔离，较旧修订不能复活 | `src/lightbooking/lighting_holds/service.py` | `tests/test_lighting_holds.py::test_conflicting_revision_is_quarantined` |
| TRAP-19 | 业务锁优先，未获准的单据不消耗资源 | `src/lightbooking/gear_reuse/service.py` | `tests/test_gear_reuse.py::test_prohibited_entries_never_spend` |
| TRAP-26 | 使用过期版本登记被拒，保留前次结果 | `src/lightbooking/hold_registry/service.py` | `tests/test_hold_registry.py::test_stale_generation_keeps_prior` |
| TRAP-32 | 零方差业务特征仍有有界尺度 | `src/lightbooking/booking_signals/service.py` | `tests/test_booking_signals.py::test_zero_variance_uses_unit_scale` |
| TRAP-42 | 训练冻结后到达的单据或回执不会回填 | `src/lightbooking/booking_signals/service.py` | `tests/test_booking_signals.py::test_future_and_late_measurements_do_not_fit` |
| TRAP-43 | 训练与独立回放的单据按时段隔离 | `src/lightbooking/shoot_holdout/service.py` | `tests/test_shoot_holdout.py::test_holdout_separates_ordered_periods` |
| TRAP-44 | 稀疏或常量参考出现越界值时拦住自动分派 | `src/lightbooking/client_mix/service.py` | `tests/test_client_mix.py::test_constant_distribution_detects_outside` |
| TRAP-53 | 同批重排仍得到相同证据和决策 | `src/lightbooking/checkout_reconcile/service.py` | `tests/test_checkout_reconcile.py::test_report_is_permutation_invariant` |
| TRAP-54 | 单笔推理与合并调用的结果一致 | `src/lightbooking/rental_hist_bayes/service.py` | `tests/test_rental_hist_bayes.py::test_score_is_batch_invariant` |
