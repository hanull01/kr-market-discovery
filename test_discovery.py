import json
import tempfile
import unittest
from pathlib import Path

import discovery

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT / 'tests' / 'fixtures'
CLOCK = lambda: '2026-09-24T10:10:00+09:00'

class DiscoveryTests(unittest.TestCase):
    def inputs(self): return discovery.load_inputs(input_dir=FIXTURES)
    def config(self): return discovery.load_config()

    def test_fresh_input_and_ranking_union_derived_rank(self):
        latest, context = discovery.build_outputs(self.inputs(), self.config(), CLOCK)
        self.assertEqual(latest['status'], 'OK'); self.assertEqual(latest['candidateCount'], 3)
        a = latest['candidates'][0]
        self.assertEqual(a['code'], '000001'); self.assertEqual(a['bestRanking'], 1)
        self.assertEqual(a['evidence']['rankings'][0]['derivedRank'], 1)
        self.assertIn('NAME_MISMATCH', a['warnings'])
        self.assertEqual(context['rankingCandidateCounts']['volume'], 2)

    def test_family_dedupe_bucket_and_deterministic_order(self):
        latest, _ = discovery.build_outputs(self.inputs(), self.config(), CLOCK)
        a = next(x for x in latest['candidates'] if x['code'] == '000001')
        self.assertEqual(a['familyCount'], 4); self.assertEqual(a['bucket'], 'MULTI_FACTOR')
        self.assertEqual([x['code'] for x in latest['candidates']], ['000001','000003','000002'])

    def test_investor_states_and_raw_fields(self):
        latest, context = discovery.build_outputs(self.inputs(), self.config(), CLOCK)
        candidates = {x['code']: x for x in latest['candidates']}
        self.assertEqual(candidates['000001']['investorState'], 'BOTH_BUY')
        self.assertEqual(candidates['000002']['investorState'], 'NONE')
        self.assertEqual(candidates['000003']['investorState'], 'NONE')
        self.assertEqual(candidates['000001']['evidence']['investors'][0]['accTradeAmount'], 100)
        self.assertEqual(context['BOTH_BUYCount'], 1)
        self.assertEqual(discovery.investor_state({'FOREIGNER':'BUY','ORGANIZATION':'SELL'}), 'BUY_SELL_CONFLICT')
        self.assertEqual(discovery.investor_state({'FOREIGNER':'SELL','ORGANIZATION':'SELL'}), 'BOTH_SELL')
        self.assertEqual(discovery.investor_state({'FOREIGNER':'BUY'}), 'FOREIGN_ONLY_BUY')
        self.assertEqual(discovery.investor_state({'ORGANIZATION':'BUY'}), 'ORGANIZATION_ONLY_BUY')

    def test_industry_breadth_and_zero_total(self):
        rows = discovery.industry_context(self.inputs()['industries'], self.config())
        self.assertEqual([x['state'] for x in rows], ['BROAD_STRENGTH','WEAK','MIXED'])
        self.assertIsNone(rows[-1]['advanceRatio'])

    def test_stale_missing_and_partial(self):
        inputs = self.inputs(); stale = discovery.validate_inputs(inputs, self.config(), lambda: '2026-09-24T11:00:00+09:00')
        self.assertEqual(stale['status'], 'STALE')
        with self.assertRaises(discovery.InputError): discovery.load_inputs(input_dir=ROOT / 'missing')
        inputs['manifest']['status'] = 'PARTIAL'; inputs['manifest']['datasets']['rankings']['status'] = 'PARTIAL'
        latest, _ = discovery.build_outputs(inputs, self.config(), CLOCK)
        self.assertEqual(latest['status'], 'PARTIAL'); self.assertIn('PARTIAL_SOURCE_DATA', latest['warnings'])
        inputs['manifest']['status'] = 'ERROR'
        with self.assertRaises(discovery.InputError): discovery.validate_inputs(inputs, self.config(), CLOCK)

    def test_theme_unused_no_recommendation_fields(self):
        latest, _ = discovery.build_outputs(self.inputs(), self.config(), CLOCK)
        serial = json.dumps(latest)
        self.assertNotIn('theme', serial.lower()); self.assertNotIn('targetPrice', serial); self.assertNotIn('buyAction', serial)

    def test_atomic_output_and_no_write(self):
        latest, context = discovery.build_outputs(self.inputs(), self.config(), CLOCK)
        with tempfile.TemporaryDirectory() as td:
            output = Path(td); discovery.write_outputs(latest, context, output)
            self.assertTrue((output/'candidates/latest.json').exists())
            self.assertTrue((output/'candidates/latest-lite.json').exists())
            self.assertTrue((output/'market-context/latest.json').exists())
            lite = json.loads((output/'candidates/latest-lite.json').read_text())
            self.assertNotIn('evidence', lite['candidates'][0])

    def test_no_write_run_creates_no_files(self):
        with tempfile.TemporaryDirectory() as td:
            discovery.run(input_dir=FIXTURES, output_dir=Path(td), no_write=True, clock=CLOCK)
            self.assertEqual(list(Path(td).iterdir()), [])

    def test_sell_and_both_sell_do_not_raise_bucket(self):
        rankings = {'rankings': [{'name': 'trading_value', 'rows': [{'code': '000001', 'name': 'A'}]},
                                 {'name': 'volume', 'rows': [{'code': '000001', 'name': 'A'}]}]}
        investors = {'investors': [{'investorType': 'FOREIGNER', 'buy': [], 'sell': [{'code': '000001'}]},
                                  {'investorType': 'ORGANIZATION', 'buy': [], 'sell': [{'code': '000001'}]}]}
        candidates, _, _ = discovery.build_candidates(rankings, investors)
        row = candidates[0]
        self.assertEqual(row['supportingFamilies'], ['LIQUIDITY', 'VOLUME'])
        self.assertEqual(row['bucket'], 'TWO_FACTOR')
        self.assertIn('BOTH_SELL', row['cautionSignals'])
        self.assertNotIn('INVESTOR_BUY', row['supportingFamilies'])

    def test_both_buy_single_investor_family_and_conflict_exclusion(self):
        rankings = {'rankings': [{'name': 'trading_value', 'rows': [{'code': '1', 'name': 'A'}]}]}
        both_buy = {'investors': [{'investorType': 'FOREIGNER', 'buy': [{'code': '1'}], 'sell': []},
                                  {'investorType': 'ORGANIZATION', 'buy': [{'code': '1'}], 'sell': []}]}
        row = discovery.build_candidates(rankings, both_buy)[0][0]
        self.assertEqual(row['supportingFamilyCount'], 2); self.assertIn('BOTH_BUY', row['signals'])
        conflict = {'investors': [{'investorType': 'FOREIGNER', 'buy': [{'code': '1'}], 'sell': []},
                                  {'investorType': 'ORGANIZATION', 'buy': [], 'sell': [{'code': '1'}]}]}
        row = discovery.build_candidates(rankings, conflict)[0][0]
        self.assertEqual(row['supportingFamilyCount'], 1); self.assertIn('BUY_SELL_CONFLICT', row['cautionSignals'])

    def test_unusual_source_code_preserved_and_integrity_checked(self):
        rankings = {'rankings': [{'name': 'trading_value', 'rows': [{'code': '0010S0', 'name': 'X', 'source': {'itemcode': '0010S0'}}]}]}
        row = discovery.build_candidates(rankings, {'investors': []})[0][0]
        self.assertEqual(row['code'], '0010S0'); self.assertEqual(row['evidence']['rankings'][0]['sourceItemcode'], '0010S0')
        self.assertIn('UNUSUAL_CODE_FORMAT', row['cautionSignals'])

    def test_history_snapshot_identity_index_and_latest_update(self):
        latest, context = discovery.build_outputs(self.inputs(), self.config(), CLOCK)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); discovery.write_outputs(latest, context, root); discovery.write_outputs(latest, context, root)
            index = json.loads((root / 'history/index.json').read_text())
            self.assertEqual(len(index), 1); self.assertTrue((root / 'history/2026-09-24/100000/candidates.json').exists())
            self.assertTrue((root / 'candidates/latest.json').exists())
            self.assertTrue((root / 'summary/latest.json').exists())

    def snapshot(self, stamp, bucket='SINGLE_FACTOR', cautions=()):
        return {'generatedAt': stamp, 'sourceGeneratedAt': stamp, 'status': 'OK', 'candidateCount': 1,
                'enrichmentEligibleCount': bucket != 'SINGLE_FACTOR',
                'bucketCounts': {'MULTI_FACTOR': bucket == 'MULTI_FACTOR', 'TWO_FACTOR': bucket == 'TWO_FACTOR', 'SINGLE_FACTOR': bucket == 'SINGLE_FACTOR'},
                'candidates': [{'code': '000001', 'name': 'A', 'bucket': bucket, 'supportingFamilyCount': discovery.BUCKET_STRENGTH[bucket], 'cautionSignals': list(cautions)}]}

    def test_summary_new_strengthening_weakening_exited_reentered_and_duplicate(self):
        base = '2026-09-24T'
        one = self.snapshot(base + '09:00:00+09:00')
        two = self.snapshot(base + '09:15:00+09:00', 'TWO_FACTOR', ('BOTH_SELL',))
        three = self.snapshot(base + '09:30:00+09:00', 'SINGLE_FACTOR')
        context = {'freshness': {'status': 'OK'}, 'industries': []}
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for item in (one, two, three): discovery.write_outputs(item, context, root)
            # A repeated source timestamp must replace, not create a fourth snapshot.
            discovery.write_outputs(three, context, root)
            summary = json.loads((root / 'summary/latest.json').read_text())
            self.assertEqual(summary['snapshotCountToday'], 3)
            self.assertEqual(summary['changes']['WEAKENING'][0]['code'], '000001')
            self.assertEqual(summary['cautionChanges']['resolved'][0]['signal'], 'BOTH_SELL')
        # Explicit history fixtures cover a gap (REENTERED) and disappearance (EXITED).
        active = self.snapshot(base + '10:00:00+09:00')
        exited = dict(active, candidates=[], candidateCount=0)
        changes, _ = discovery._candidate_changes([(one['sourceGeneratedAt'], one, context), (exited['sourceGeneratedAt'], exited, context)])
        self.assertEqual(changes['EXITED'][0]['state'], 'EXITED')
        changes, _ = discovery._candidate_changes([(one['sourceGeneratedAt'], one, context), (exited['sourceGeneratedAt'], exited, context), (active['sourceGeneratedAt'], active, context)])
        self.assertEqual(changes['REENTERED'][0]['state'], 'REENTERED')

    def test_summary_first_snapshot_new_and_not_ready_enrichment(self):
        latest, context = discovery.build_outputs(self.inputs(), self.config(), CLOCK)
        with tempfile.TemporaryDirectory() as td:
            discovery.write_outputs(latest, context, td)
            summary = json.loads((Path(td) / 'summary/latest.json').read_text())
        self.assertEqual(summary['snapshotCountToday'], 1)
        self.assertEqual(len(summary['changes']['NEW']), 3)
        self.assertEqual(summary['industryContext']['membershipStatus'], 'NOT_READY')
        self.assertEqual(summary['multiPeriodInvestorEvidence']['supportedPeriodTypes'], ['DAY'])
        self.assertEqual(summary['multiPeriodInvestorEvidence']['notReadyPeriodTypes'], ['WEEK', 'MONTH', 'THREE_MONTH'])

    def test_multi_period_raw_names_and_stale_summary(self):
        latest, context = discovery.build_outputs(self.inputs(), self.config(), CLOCK)
        item = latest['multiPeriodInvestorEvidence']['items'][0]['periods'][0]['directions'][0]
        self.assertIn('accTradeVolume', item); self.assertIn('accTradeAmount', item)
        stale, stale_context = discovery.build_outputs(self.inputs(), self.config(), lambda: '2026-09-24T11:00:00+09:00')
        with tempfile.TemporaryDirectory() as td:
            discovery.write_outputs(stale, stale_context, td)
            self.assertEqual(json.loads((Path(td) / 'summary/latest.json').read_text())['status'], 'STALE')

    def test_verified_multi_period_and_industry_membership_are_used(self):
        inputs = self.inputs()
        period_entry = {'status': 'OK', 'investors': [
            {'investorType': 'FOREIGNER', 'buy': [{'code': '000001', 'accTradeVolume': 50, 'accTradeAmount': 500,
                                                   'bizdateFrom': '20260917', 'bizdateTo': '20260923', 'toRankingAt': None}], 'sell': []},
            {'investorType': 'ORGANIZATION', 'buy': [], 'sell': []}]}
        inputs['investors']['multiPeriod'] = {'periods': {period: dict(period_entry) for period in ('WEEK', 'MONTH', 'THREE_MONTH')}}
        inputs['membership'] = {'status': 'OK', 'generatedAt': CLOCK(),
                                'byCode': {'000001': [{'id': '1', 'name': '강세'}]}}
        latest, _ = discovery.build_outputs(inputs, self.config(), CLOCK)
        candidate = next(x for x in latest['candidates'] if x['code'] == '000001')
        self.assertEqual(latest['multiPeriodInvestorEvidence']['supportedPeriodTypes'], ['DAY', 'WEEK', 'MONTH', 'THREE_MONTH'])
        self.assertEqual(candidate['industry'], {'status': 'READY', 'id': '1', 'name': '강세', 'state': 'BROAD_STRENGTH', 'contextSignal': 'BROAD_STRENGTH'})
        periods = {x['periodType']: x for x in latest['multiPeriodInvestorEvidence']['items'][0]['periods']}
        self.assertEqual(periods['WEEK']['directions'][0]['accTradeAmount'], 500)
        self.assertNotIn('netBuy', periods['WEEK']['directions'][0])

    def test_membership_error_falls_back_to_not_ready(self):
        inputs = self.inputs(); inputs['membership'] = {'status': 'ERROR', 'reason': 'UPSTREAM_ERROR'}
        latest, _ = discovery.build_outputs(inputs, self.config(), CLOCK)
        self.assertEqual(latest['industryMembership']['status'], 'ERROR')
        self.assertEqual(latest['candidates'][0]['industry']['status'], 'NOT_READY')

    def test_stale_membership_falls_back_to_not_ready(self):
        inputs = self.inputs(); inputs['membership'] = {'status': 'OK', 'generatedAt': '2026-09-22T09:00:00+09:00',
                                                        'byCode': {'000001': [{'id': '1', 'name': '강세'}]}}
        latest, _ = discovery.build_outputs(inputs, self.config(), CLOCK)
        self.assertEqual(latest['industryMembership']['reason'], 'STALE_CACHE')
        self.assertEqual(latest['candidates'][0]['industry']['status'], 'NOT_READY')

    def test_summary_industry_context_change(self):
        latest, context = discovery.build_outputs(self.inputs(), self.config(), CLOCK)
        earlier = dict(context, industries=[dict(row) for row in context['industries']])
        earlier['industries'][0]['state'] = 'MIXED'
        with tempfile.TemporaryDirectory() as td:
            first = dict(latest, sourceGeneratedAt='2026-09-24T09:45:00+09:00', generatedAt='2026-09-24T09:45:00+09:00')
            discovery.write_outputs(first, earlier, td)
            discovery.write_outputs(latest, context, td)
            changes = json.loads((Path(td) / 'summary/latest.json').read_text())['industryContext']['changes']
        self.assertEqual(changes, [{'id': '1', 'name': '강세', 'from': 'MIXED', 'to': 'BROAD_STRENGTH'}])

    def test_same_bucket_family_count_controls_strength(self):
        first = self.snapshot('2026-09-24T09:00:00+09:00', 'MULTI_FACTOR')
        second = self.snapshot('2026-09-24T09:15:00+09:00', 'MULTI_FACTOR')
        second['candidates'][0]['supportingFamilyCount'] = 4
        first['candidates'][0]['supportingFamilyCount'] = 3
        changes, _ = discovery._candidate_changes([(first['sourceGeneratedAt'], first, {}), (second['sourceGeneratedAt'], second, {})])
        self.assertEqual(changes['STRENGTHENING'][0]['code'], '000001')

if __name__ == '__main__': unittest.main()
