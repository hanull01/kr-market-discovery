# Prior-art review

Reviewed before implementation on 2026-09-24.

| Source | Code/document reviewed | Adopted | Not adopted |
| --- | --- | --- | --- |
| [jwlee-collab/krx-stock](https://github.com/jwlee-collab/krx-stock) | Market-wide universe pipeline and explicit daily feature tables | Separate input, feature/evidence, and output layers | Scores, backtests, and portfolio selection; this project is discovery only |
| [xang1234 stock-screener](https://github.com/matbar850/stock-screener-xang) | Broad screening and breadth-oriented presentation | Market context is kept separate from a candidate row | Its large filter set, AI chat, and theme discovery; v1 avoids unvalidated enrichment |
| [Knext/StockHunter](https://github.com/Knext/StockHunter) | Whole-market sequential technical screen and API/report separation | Deterministic, inspectable outputs | Buy-signal stages and technical indicator strategy logic |
| [Korea Investment open-trading-api](https://github.com/koreainvestment/open-trading-api) | Official examples distinguish market data from authenticated account/order flows | Preserve investor-flow evidence and keep data handling explicit | Authentication, account data, orders, and automatic trading |

The chosen model uses ranking, investor, and market-breadth evidence families rather than a numeric score. It preserves upstream field names and labels all output as “additional research candidates.”

## v1.2 research gate

| Question | Public evidence reviewed | Gate result | v1.2 decision |
| --- | --- | --- | --- |
| Investor periods | `dd3ok/naverstock-api-skill` catalogs `trend-foreign-org`; PotatoWhite/fin-invest preserves the raw foreign/institutional flow fields. | Live-verified 2026-09-24: FOREIGNER/ORGANIZATION × WEEK/MONTH/THREE_MONTH accepted; 20 rows per buy/sell list on pages 0–4, then both empty on page 5. | Relay retains `accTradeVolume`/`accTradeAmount` and exposes all verified periods under a backward-compatible `multiPeriod` object. |
| Stock-to-industry membership | dd3ok's category examples distinguish ranking and member-list pagination. | Live-verified 2026-09-24: `/upjong/list` yielded 79 IDs; `/upjong/{no}/stocklist` uses `itemcode`/`itemname`, zero-based `startIdx`, and empty-array termination. The proposed `/domestic/sector/item/list` was HTTP 404 HTML. | A 24-hour cache maps `byCode` to a single verified industry; Discovery falls back to `NOT_READY` on missing, partial, stale, or error data. |
| Program/market-wide flow | `dd3ok/naverstock-api-skill` lists trend-program and aggregate requests; osori-workbench/stock-tracker uses other `stock.naver.com` domestic APIs in intraday collection. | Endpoint existence documented only; no contract probe in this gate. | Do not add it. Existing ranking + investor + breadth evidence remains the bounded input. |

Live checks were attempted against `m.stock.naver.com` from the implementation
environment, but DNS resolution was unavailable. This is treated as a failed
verification, not evidence that an undocumented endpoint works.
