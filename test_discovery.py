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

if __name__ == '__main__': unittest.main()
