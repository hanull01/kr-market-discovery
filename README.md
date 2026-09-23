# KR Market Discovery

Candidate discovery for further research using market-wide upstream snapshots. This is not a stock recommendation engine, trading signal, price target, stop-loss system, or order tool.

It consumes production JSON from `hanull01/naver-krx-universe-relay`; it does not call NAVER market APIs and does not depend on a monitoring Universe.

```bash
python3 discovery.py all --no-write
python3 discovery.py all
python3 discovery.py all --input-dir tests/fixtures --no-write
```

Output ordering is deterministic—evidence family count, then best derived ranking, then code—for review and stable diffs only. It is not an investment priority.

Future workflow: candidate → ChatGPT analysis → user approval → `naver-krx-universe-relay` `universe_cli.py add-stock`. No automatic promotion occurs.
