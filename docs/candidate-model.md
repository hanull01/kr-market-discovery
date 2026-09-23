# Candidate model

Positive sources are trading value, volume, volume surge, 52-week high, and gainers. Losers and market cap are context-only. A candidate is the union of those ranking codes; investor rows enrich only that union.

Supporting families are `LIQUIDITY`, `VOLUME`, `MOMENTUM`, and `INVESTOR_BUY`. Buckets (`SINGLE_FACTOR`, `TWO_FACTOR`, `MULTI_FACTOR`) use supporting families only and group follow-up work; they are not investment grades. `FOREIGN_SELL`, `INSTITUTION_SELL`, `BOTH_SELL`, and `BUY_SELL_CONFLICT` are caution signals, not supporting evidence. A conflict preserves BUY evidence but conservatively does not receive `INVESTOR_BUY` support.

Investor direction comes solely from buy/sell container membership. `accTradeVolume` and `accTradeAmount` are retained without renaming because upstream semantics remain partial. Industry context describes breadth only; no stock-to-industry membership is inferred. Theme and news are deliberately unused in v1.

`enrichmentEligible` is true only for `MULTI_FACTOR` and `TWO_FACTOR`; it controls follow-up research workload, not an investment decision. History snapshots use the KST date and time of `sourceGeneratedAt`, so rerunning the same upstream identity replaces the same snapshot path. Future validation may add price outcomes at +1D/+3D/+5D only after a separate future-price lookup design.
