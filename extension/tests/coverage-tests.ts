import test from 'node:test';
import assert from 'node:assert/strict';
import {parseCoverage,coverageSummary} from '../src/chapter/coverage';
test('coverage parsing is additive, bounded numeric data and optional for older backends',()=>{
  assert.equal(parseCoverage(undefined),undefined);
  assert.deepEqual(parseCoverage({bubble_rendered:3,not_detected_estimate:null}),{bubble_rendered:3});
  assert.throws(()=>parseCoverage({bubble_rendered:-1}));
  assert.throws(()=>parseCoverage({sfx_preserved:'4'}));
});
test('chapter coverage separates pages from preserved block categories',()=>{
  const message=coverageSummary([{skipped:3,coverage:{bubble_preserved:1,artwork_text_preserved:1,sfx_preserved:1}},
    {skipped:2},{skipped:0}]);
  assert.match(message,/2 rendered pages/);
  assert.match(message,/2 dialogue\/artwork/);assert.match(message,/1 likely SFX/);assert.match(message,/2 unknown/);
  assert.equal(coverageSummary([{skipped:0}]),'');
  assert.match(coverageSummary([{skipped:2,coverage:{}}]),/2 unknown/);
});
