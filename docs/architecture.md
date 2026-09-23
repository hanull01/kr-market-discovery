# Architecture

`upstream JSON → freshness gate → evidence merge → candidate/context JSON`

The input adapter supports GitHub raw URLs and local fixture directories. Discovery logic receives already-decoded JSON, so unit tests make no network calls. `generatedAt` describes this consumer run; `sourceGeneratedAt` remains the upstream collector time.

An upstream `ERROR` dataset stops processing. `PARTIAL` data is retained with `PARTIAL_SOURCE_DATA`. Stale input produces an empty `STALE` output and does not generate candidates.
