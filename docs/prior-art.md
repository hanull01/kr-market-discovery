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
| Investor periods | Public Naver API catalog/implementation references show investor ranking requests with a `periodType`, but do not provide a stable, authoritative contract for `WEEK`, `MONTH`, and `THREE_MONTH`. | Not live-verified | Reuse the relay's proven DAY input only. Keep `accTradeVolume` and `accTradeAmount` raw. Mark other periods `NOT_READY`. |
| Stock-to-industry membership | Public Naver integrations expose peer/industry panels, but the member-list path and response keys were not stable enough to establish a bounded collection contract. | Not live-verified | Do not scrape or infer membership. Candidate `industry` is explicitly `NOT_READY`; market-wide industry breadth remains available. |
| Program/market-wide flow | Public implementations expose program-trend and aggregate investor panels, but their request/body contracts were not independently verified. | Not live-verified | Do not add it. Existing ranking + investor + breadth evidence remains the bounded input. |

Live checks were attempted against `m.stock.naver.com` from the implementation
environment, but DNS resolution was unavailable. This is treated as a failed
verification, not evidence that an undocumented endpoint works.
