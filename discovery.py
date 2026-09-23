"""Candidate discovery for further research, not investment advice or trading."""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DEFAULT_BASE = 'https://raw.githubusercontent.com/hanull01/naver-krx-universe-relay/main/'
KST = ZoneInfo('Asia/Seoul')
FILES = {'manifest': 'data/market/manifest.json', 'rankings': 'data/market/rankings.json',
         'industries': 'data/market/industries.json', 'investors': 'data/market/investor-flow.json'}
POSITIVE = ('trading_value', 'volume', 'volume_surge', 'high_52week', 'gainers')
FAMILIES = {'trading_value': 'LIQUIDITY', 'volume': 'VOLUME', 'volume_surge': 'VOLUME',
            'high_52week': 'MOMENTUM', 'gainers': 'MOMENTUM'}

class InputError(RuntimeError): pass

def now(): return datetime.now(KST).isoformat()
def err(exc): return {'type': type(exc).__name__, 'message': str(exc)}
def read_json(location, opener=urlopen):
    if location.startswith(('http://', 'https://')):
        request = Request(location, headers={'User-Agent': 'kr-market-discovery/1.0', 'Accept': 'application/json'})
        try:
            with opener(request, timeout=20) as response:
                if not 200 <= response.status < 300: raise InputError(f'HTTP {response.status}: {location}')
                text = response.read().decode('utf-8')
        except Exception as exc:
            raise InputError(f'cannot fetch {location}: {exc}') from exc
    else:
        try: text = Path(location).read_text(encoding='utf-8')
        except OSError as exc: raise InputError(f'missing input: {location}') from exc
    try: return json.loads(text)
    except json.JSONDecodeError as exc: raise InputError(f'invalid JSON: {location}') from exc

def input_locations(input_base=None, input_dir=None):
    if input_dir:
        return {key: str(Path(input_dir) / Path(path).name) for key, path in FILES.items()}
    base = input_base or DEFAULT_BASE
    return {key: base.rstrip('/') + '/' + path for key, path in FILES.items()}

def load_inputs(input_base=None, input_dir=None, reader=read_json):
    return {key: reader(path) for key, path in input_locations(input_base, input_dir).items()}

def parse_time(value):
    if not isinstance(value, str): raise InputError('manifest generatedAt missing')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None: raise InputError('manifest generatedAt lacks timezone')
    return parsed

def validate_inputs(inputs, config, clock=now):
    manifest = inputs.get('manifest')
    if not isinstance(manifest, dict): raise InputError('manifest must be an object')
    if manifest.get('status') == 'ERROR': raise InputError('manifest status ERROR')
    generated = parse_time(manifest.get('generatedAt'))
    current = parse_time(clock())
    age_minutes = (current.astimezone(timezone.utc) - generated.astimezone(timezone.utc)).total_seconds() / 60
    if age_minutes > config['maxInputAgeMinutes']:
        return {'status': 'STALE', 'sourceGeneratedAt': manifest['generatedAt'], 'ageMinutes': round(age_minutes, 2), 'warnings': ['STALE_SOURCE']}
    warnings = []
    for name, details in manifest.get('datasets', {}).items():
        if details.get('status') == 'ERROR': raise InputError(f'dataset {name} status ERROR')
        if details.get('status') == 'PARTIAL': warnings.append('PARTIAL_SOURCE_DATA')
    if manifest.get('status') == 'PARTIAL': warnings.append('PARTIAL_SOURCE_DATA')
    return {'status': 'PARTIAL' if warnings else 'OK', 'sourceGeneratedAt': manifest['generatedAt'], 'ageMinutes': round(age_minutes, 2), 'warnings': sorted(set(warnings))}

def stock_evidence(row, ranking, rank):
    source = row.get('source') if isinstance(row.get('source'), dict) else {}
    return {'source': ranking, 'derivedRank': rank, 'price': row.get('price'), 'changeRate': row.get('changeRate'),
            'volume': row.get('volume'), 'tradingValue': row.get('tradingValue'),
            'sourceItemcode': source.get('itemcode')}

def build_candidates(rankings, investors, base_warnings=()):
    by_name = {entry.get('name'): entry for entry in rankings.get('rankings', []) if isinstance(entry, dict)}
    candidates, ranking_counts = {}, {}
    for ranking in POSITIVE:
        rows = by_name.get(ranking, {}).get('rows', [])
        ranking_counts[ranking] = len(rows) if isinstance(rows, list) else 0
        for index, row in enumerate(rows if isinstance(rows, list) else [], 1):
            code, name = row.get('code'), row.get('name')
            if not code or not name: continue
            candidate = candidates.setdefault(code, {'code': code, 'name': name, 'signals': [], 'warnings': list(base_warnings),
                                                     'evidence': {'rankings': [], 'investors': []}})
            if candidate['name'] != name:
                candidate['warnings'].append('NAME_MISMATCH')
            candidate['evidence']['rankings'].append(stock_evidence(row, ranking, index))
            candidate['signals'].append({'trading_value': 'HIGH_TRADING_VALUE', 'volume': 'HIGH_VOLUME',
                                         'volume_surge': 'VOLUME_SURGE', 'high_52week': 'HIGH_52WEEK', 'gainers': 'TOP_GAINER'}[ranking])
    positions = {}
    for entry in investors.get('investors', []):
        if not isinstance(entry, dict): continue
        investor_type = entry.get('investorType')
        for side, key, signal in (('BUY', 'buy', f'{investor_type}_BUY'), ('SELL', 'sell', f'{investor_type}_SELL')):
            for rank, row in enumerate(entry.get(key, []) if isinstance(entry.get(key), list) else [], 1):
                code = row.get('code')
                if not code: continue
                positions.setdefault(code, {})[investor_type] = side
                if code not in candidates: continue
                candidates[code]['signals'].append(signal)
                candidates[code]['evidence']['investors'].append({'investorType': investor_type, 'side': side, 'derivedRank': rank,
                    'accTradeVolume': row.get('accTradeVolume'), 'accTradeAmount': row.get('accTradeAmount')})
    for candidate in candidates.values():
        position = positions.get(candidate['code'], {})
        foreign, org = position.get('FOREIGNER'), position.get('ORGANIZATION')
        state = investor_state(position); candidate['investorState'] = state
        if state == 'BOTH_BUY': candidate['signals'].append('BOTH_BUY')
        if state == 'BUY_SELL_CONFLICT': candidate['signals'].append('BUY_SELL_CONFLICT'); candidate['warnings'].append('BUY_SELL_CONFLICT')
        signals = set(candidate['signals'])
        if 'VOLUME_SURGE' in signals and 'TOP_GAINER' in signals: candidate['warnings'].append('VOLUME_SURGE_AND_GAIN')
        supporting = {FAMILIES[e['source']] for e in candidate['evidence']['rankings']}
        cautions = []
        if state in ('BOTH_BUY', 'FOREIGN_ONLY_BUY', 'ORGANIZATION_ONLY_BUY'):
            supporting.add('INVESTOR_BUY')
        if foreign == 'SELL': cautions.append('FOREIGN_SELL')
        if org == 'SELL': cautions.append('INSTITUTION_SELL')
        if state == 'BOTH_SELL': cautions.append('BOTH_SELL')
        if state == 'BUY_SELL_CONFLICT': cautions.append('BUY_SELL_CONFLICT')
        for evidence in candidate['evidence']['rankings']:
            source_itemcode = evidence.get('sourceItemcode')
            if source_itemcode is not None and source_itemcode != candidate['code']:
                cautions.append('SOURCE_CODE_MISMATCH')
            if source_itemcode == candidate['code'] and not re.fullmatch(r'\d{6}', candidate['code']):
                cautions.append('UNUSUAL_CODE_FORMAT')
        candidate['supportingFamilies'] = sorted(supporting)
        candidate['supportingFamilyCount'] = len(supporting)
        candidate['familyCount'] = len(supporting)  # Backward-compatible alias, now supporting-only.
        candidate['bucket'] = 'MULTI_FACTOR' if len(supporting) >= 3 else 'TWO_FACTOR' if len(supporting) == 2 else 'SINGLE_FACTOR'
        candidate['enrichmentEligible'] = candidate['bucket'] != 'SINGLE_FACTOR'
        candidate['enrichmentReason'] = sorted(supporting)
        candidate['cautionSignals'] = sorted(set(cautions))
        candidate['signals'] = sorted(set(candidate['signals'])); candidate['warnings'] = sorted(set(candidate['warnings']))
        candidate['bestRanking'] = min((e['derivedRank'] for e in candidate['evidence']['rankings']), default=None)
    ordered = sorted(candidates.values(), key=lambda c: (-c['supportingFamilyCount'], c['bestRanking'], c['code']))
    return ordered, ranking_counts, positions

def investor_state(position):
    foreign, org = position.get('FOREIGNER'), position.get('ORGANIZATION')
    if foreign == org == 'BUY': return 'BOTH_BUY'
    if foreign == 'BUY' and org is None: return 'FOREIGN_ONLY_BUY'
    if org == 'BUY' and foreign is None: return 'ORGANIZATION_ONLY_BUY'
    if foreign and org and foreign != org: return 'BUY_SELL_CONFLICT'
    if foreign == org == 'SELL': return 'BOTH_SELL'
    return 'NONE'

def industry_context(industries, config):
    rows = []
    for row in industries.get('industries', []):
        total, rising, falling = row.get('totalStocks') or 0, row.get('risingStocks') or 0, row.get('fallingStocks') or 0
        advance, decline = (rising / total, falling / total) if total else (None, None)
        state = 'MIXED' if advance is None else 'BROAD_STRENGTH' if advance >= config['industry']['broadAdvanceRatio'] else 'WEAK' if advance <= config['industry']['weakAdvanceRatio'] else 'MIXED'
        rows.append({'id': row.get('id'), 'name': row.get('name'), 'advanceRatio': advance, 'declineRatio': decline, 'state': state})
    return rows

def build_outputs(inputs, config, clock=now):
    freshness = validate_inputs(inputs, config, clock)
    generated = clock()
    if freshness['status'] == 'STALE':
        empty = {'generatedAt': generated, 'sourceGeneratedAt': freshness['sourceGeneratedAt'], 'status': 'STALE', 'candidateCount': 0,
                 'enrichmentEligibleCount': 0, 'bucketCounts': {'MULTI_FACTOR': 0, 'TWO_FACTOR': 0, 'SINGLE_FACTOR': 0},
                 'warnings': freshness['warnings'], 'candidates': [],
                 'multiPeriodInvestorEvidence': {'status': 'NOT_READY', 'supportedPeriodTypes': [], 'notReadyPeriodTypes': ['DAY', 'WEEK', 'MONTH', 'THREE_MONTH']},
                 'industryMembership': {'status': 'NOT_READY', 'reason': 'STALE_SOURCE'}}
        return empty, {'generatedAt': generated, 'sourceGeneratedAt': freshness['sourceGeneratedAt'], 'status': 'STALE', 'freshness': freshness, 'warnings': freshness['warnings']}
    candidates, counts, positions = build_candidates(inputs['rankings'], inputs['investors'], freshness['warnings'])
    context_industries = industry_context(inputs['industries'], config)
    bucket_counts = {bucket: sum(c['bucket'] == bucket for c in candidates) for bucket in ('MULTI_FACTOR', 'TWO_FACTOR', 'SINGLE_FACTOR')}
    caution_counts = {signal: sum(signal in c['cautionSignals'] for c in candidates) for signal in ('BOTH_SELL', 'BUY_SELL_CONFLICT', 'RAPID_MOVE')}
    context = {'generatedAt': generated, 'sourceGeneratedAt': freshness['sourceGeneratedAt'], 'status': freshness['status'], 'freshness': freshness,
               'rankingCandidateCounts': counts, 'rankingOverlapCount': sum(1 for c in candidates if len(c['evidence']['rankings']) > 1),
               'FOREIGNERBuyCount': sum(1 for p in positions.values() if p.get('FOREIGNER') == 'BUY'),
               'ORGANIZATIONBuyCount': sum(1 for p in positions.values() if p.get('ORGANIZATION') == 'BUY'),
               'BOTH_BUYCount': sum(1 for p in positions.values() if investor_state(p) == 'BOTH_BUY'),
               'BUY_SELL_CONFLICTCount': sum(1 for p in positions.values() if investor_state(p) == 'BUY_SELL_CONFLICT'),
               'industriesTotal': len(context_industries), 'broadStrengthIndustryCount': sum(r['state'] == 'BROAD_STRENGTH' for r in context_industries),
               'weakIndustryCount': sum(r['state'] == 'WEAK' for r in context_industries), 'candidateCount': len(candidates),
               'enrichmentEligibleCount': sum(c['enrichmentEligible'] for c in candidates), 'bucketCounts': bucket_counts,
               'cautionCounts': caution_counts, 'warnings': freshness['warnings'], 'industries': context_industries}
    # The relay currently supplies a verified DAY ranking only.  Keep the raw
    # amount/volume names in candidate evidence; do not infer a net-buy value.
    multi_period = build_multi_period_evidence(candidates)
    for candidate in candidates:
        candidate['industry'] = {'status': 'NOT_READY', 'reason': 'NAVER_MEMBER_CONTRACT_UNVERIFIED',
                                 'id': None, 'name': None, 'state': None, 'contextSignal': 'NOT_READY'}
    latest = {'generatedAt': generated, 'sourceGeneratedAt': freshness['sourceGeneratedAt'], 'status': freshness['status'], 'candidateCount': len(candidates),
              'enrichmentEligibleCount': sum(c['enrichmentEligible'] for c in candidates), 'bucketCounts': bucket_counts,
              'cautionCounts': caution_counts, 'warnings': freshness['warnings'], 'candidates': candidates}
    latest['multiPeriodInvestorEvidence'] = multi_period
    latest['industryMembership'] = {'status': 'NOT_READY', 'reason': 'NAVER_MEMBER_CONTRACT_UNVERIFIED'}
    return latest, context

def build_multi_period_evidence(candidates):
    """Describe only the periods actually available in the input contract.

    WEEK/MONTH/THREE_MONTH deliberately remain unavailable until a live NAVER
    contract is re-verified.  DAY is ranking direction evidence, not a claim
    about a calculated net purchase amount.
    """
    items = []
    for candidate in candidates:
        day = [row for row in candidate['evidence']['investors'] if row.get('side') in ('BUY', 'SELL')]
        if day:
            items.append({'code': candidate['code'], 'name': candidate['name'], 'periods': [{'periodType': 'DAY', 'directions': [
                {'investorType': row.get('investorType'), 'side': row.get('side'), 'accTradeVolume': row.get('accTradeVolume'),
                 'accTradeAmount': row.get('accTradeAmount')} for row in day]}], 'alignment': 'DAY_ONLY'})
    return {'status': 'PARTIAL', 'supportedPeriodTypes': ['DAY'], 'notReadyPeriodTypes': ['WEEK', 'MONTH', 'THREE_MONTH'],
            'reason': 'NAVER_PERIOD_CONTRACT_UNVERIFIED', 'items': items}

BUCKET_STRENGTH = {'SINGLE_FACTOR': 1, 'TWO_FACTOR': 2, 'MULTI_FACTOR': 3}

def _today_history(root, source_time):
    """Read unique KST snapshots from the index; ignore duplicate source times."""
    root, day = Path(root), parse_time(source_time).astimezone(KST).strftime('%Y-%m-%d')
    try: index = read_json(str(root / 'history' / 'index.json'))
    except InputError: return []
    seen, snapshots = set(), []
    for entry in sorted((row for row in index if isinstance(row, dict)), key=lambda row: row.get('sourceGeneratedAt', '')):
        stamp = entry.get('sourceGeneratedAt')
        if stamp in seen or not stamp: continue
        try:
            if parse_time(stamp).astimezone(KST).strftime('%Y-%m-%d') != day: continue
            base = root / entry['path']
            snapshots.append((stamp, read_json(str(base / 'candidates.json')), read_json(str(base / 'market-context.json'))))
            seen.add(stamp)
        except (KeyError, InputError):
            continue
    return snapshots

def _candidate_changes(snapshots):
    all_codes, tracks = set(), {}
    for index, (stamp, latest, _) in enumerate(snapshots):
        active = {row.get('code'): row for row in latest.get('candidates', []) if row.get('code')}
        all_codes.update(active)
        for code, row in active.items():
            track = tracks.setdefault(code, {'code': code, 'name': row.get('name'), 'appearances': [], 'rows': []})
            track['appearances'].append(index); track['rows'].append((stamp, row))
    current = {row.get('code'): row for row in snapshots[-1][1].get('candidates', []) if row.get('code')} if snapshots else {}
    changes = {name: [] for name in ('NEW', 'PERSISTENT', 'STRENGTHENING', 'WEAKENING', 'EXITED', 'REENTERED')}
    details = {}
    for code in sorted(all_codes):
        track, appeared = tracks[code], tracks[code]['appearances']
        active = code in current
        first, last = track['rows'][0][0], track['rows'][-1][0]
        consecutive = 0
        for position in reversed(appeared):
            if position == appeared[-1] - consecutive: consecutive += 1
            else: break
        if not active: state = 'EXITED'
        elif len(appeared) == 1: state = 'NEW'
        elif any(b - a > 1 for a, b in zip(appeared, appeared[1:])): state = 'REENTERED'
        else:
            previous = track['rows'][-2][1]
            # Bucket is the primary ordinal (MULTI > TWO > SINGLE); the
            # supporting-family count resolves changes within the same bucket.
            current_strength = (BUCKET_STRENGTH.get(current[code].get('bucket'), 0), current[code].get('supportingFamilyCount') or 0)
            previous_strength = (BUCKET_STRENGTH.get(previous.get('bucket'), 0), previous.get('supportingFamilyCount') or 0)
            state = 'STRENGTHENING' if current_strength > previous_strength else 'WEAKENING' if current_strength < previous_strength else 'PERSISTENT'
        row = current.get(code, track['rows'][-1][1])
        detail = {'code': code, 'name': row.get('name'), 'state': state, 'firstSeenAt': first, 'lastSeenAt': last,
                  'consecutiveSnapshotCount': consecutive, 'appearanceCountToday': len(appeared), 'active': active,
                  'bucket': row.get('bucket'), 'supportingFamilyCount': row.get('supportingFamilyCount'),
                  'cautionSignals': row.get('cautionSignals', [])}
        details[code] = detail; changes[state].append(detail)
    return changes, details

def build_summary(latest, context, output_dir):
    snapshots = _today_history(output_dir, latest['sourceGeneratedAt'])
    # write_outputs calls this after recording the current snapshot; fall back
    # for callers building an in-memory/no-history sample.
    if not snapshots: snapshots = [(latest['sourceGeneratedAt'], latest, context)]
    changes, details = _candidate_changes(snapshots)
    current, previous = snapshots[-1][1], snapshots[-2][1] if len(snapshots) > 1 else {'candidates': []}
    old = {row.get('code'): row for row in previous.get('candidates', [])}
    new_caution, resolved = [], []
    for code, row in {r.get('code'): r for r in current.get('candidates', [])}.items():
        before, after = set(old.get(code, {}).get('cautionSignals', [])), set(row.get('cautionSignals', []))
        for signal in sorted(after - before): new_caution.append({'code': code, 'name': row.get('name'), 'signal': signal})
        for signal in sorted(before - after): resolved.append({'code': code, 'name': row.get('name'), 'signal': signal})
    previous_context = snapshots[-2][2] if len(snapshots) > 1 else {}
    before_industry = {row.get('id'): row.get('state') for row in previous_context.get('industries', [])}
    industry_changes = [{'id': row.get('id'), 'name': row.get('name'), 'from': before_industry.get(row.get('id')), 'to': row.get('state')}
                        for row in context.get('industries', []) if before_industry.get(row.get('id')) not in (None, row.get('state'))]
    bucket_before = previous.get('bucketCounts', {})
    bucket_change = {key: latest.get('bucketCounts', {}).get(key, 0) - bucket_before.get(key, 0)
                     for key in ('MULTI_FACTOR', 'TWO_FACTOR', 'SINGLE_FACTOR')}
    highlights = []
    for label in ('NEW', 'REENTERED', 'STRENGTHENING', 'WEAKENING', 'EXITED'):
        for item in changes[label]: highlights.append({'reasonType': label, 'code': item['code'], 'name': item['name'],
            'evidence': {'bucket': item['bucket'], 'supportingFamilyCount': item['supportingFamilyCount'], 'active': item['active']}})
    return {'generatedAt': latest['generatedAt'], 'sourceGeneratedAt': latest['sourceGeneratedAt'], 'status': latest['status'],
            'freshness': context.get('freshness'), 'snapshotCountToday': len(snapshots), 'candidateCount': {'current': latest['candidateCount'], 'change': latest['candidateCount'] - previous.get('candidateCount', 0)},
            'enrichmentEligibleCount': {'current': latest['enrichmentEligibleCount'], 'change': latest['enrichmentEligibleCount'] - previous.get('enrichmentEligibleCount', 0)},
            'bucketCounts': {'current': latest.get('bucketCounts', {}), 'change': bucket_change},
            'changes': changes, 'persistentCandidates': changes['PERSISTENT'], 'cautionChanges': {'new': new_caution, 'resolved': resolved},
            'industryContext': {'membershipStatus': latest.get('industryMembership', {}).get('status'), 'changes': industry_changes},
            'multiPeriodInvestorEvidence': latest.get('multiPeriodInvestorEvidence'), 'reportHighlights': highlights}

def atomic_write(path, payload):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True); temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8'); os.replace(temp, path)

def write_outputs(latest, context, output_dir):
    root = Path(output_dir); atomic_write(root / 'candidates' / 'latest.json', latest)
    lite = {'generatedAt': latest['generatedAt'], 'sourceGeneratedAt': latest['sourceGeneratedAt'], 'status': latest['status'], 'candidateCount': latest['candidateCount'], 'warnings': latest.get('warnings', []),
            'candidates': [{key: row.get(key) for key in ('code','name','bucket','familyCount','signals','warnings','investorState','bestRanking')} for row in latest['candidates']]}
    atomic_write(root / 'candidates' / 'latest-lite.json', lite); atomic_write(root / 'market-context' / 'latest.json', context)
    if latest['status'] != 'STALE':
        source_time = parse_time(latest['sourceGeneratedAt']).astimezone(KST)
        snapshot = root / 'history' / source_time.strftime('%Y-%m-%d') / source_time.strftime('%H%M%S')
        atomic_write(snapshot / 'candidates.json', latest)
        atomic_write(snapshot / 'candidates-lite.json', lite)
        atomic_write(snapshot / 'market-context.json', context)
        index_path = root / 'history' / 'index.json'
        try: index = read_json(str(index_path))
        except InputError: index = []
        identity = latest['sourceGeneratedAt']
        entry = {'sourceGeneratedAt': identity, 'path': str(snapshot.relative_to(root)), 'candidateCount': latest['candidateCount'],
                 'enrichmentEligibleCount': latest['enrichmentEligibleCount']}
        index = [row for row in index if row.get('sourceGeneratedAt') != identity] + [entry]
        atomic_write(index_path, sorted(index, key=lambda row: row['sourceGeneratedAt']))
    atomic_write(root / 'summary' / 'latest.json', build_summary(latest, context, root))

def load_config(path=ROOT / 'config' / 'discovery.json'): return read_json(str(path))
def run(input_base=None, input_dir=None, output_dir=ROOT / 'data', no_write=False, reader=read_json, clock=now):
    inputs = load_inputs(input_base, input_dir, reader); latest, context = build_outputs(inputs, load_config(), clock)
    if not no_write: write_outputs(latest, context, output_dir)
    return latest, context

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    no_write = '--no-write' in argv
    if no_write: argv.remove('--no-write')
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('command', choices=('validate-input','candidates','market-context','all'))
    parser.add_argument('--input-base'); parser.add_argument('--input-dir'); parser.add_argument('--output-dir', default=str(ROOT / 'data'))
    args = parser.parse_args(argv); inputs = load_inputs(args.input_base, args.input_dir); freshness = validate_inputs(inputs, load_config())
    if args.command == 'validate-input': result = freshness
    else:
        latest, context = build_outputs(inputs, load_config())
        if not no_write: write_outputs(latest, context, args.output_dir)
        result = latest if args.command == 'candidates' else context if args.command == 'market-context' else {'candidates': latest, 'marketContext': context}
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == '__main__': main()
