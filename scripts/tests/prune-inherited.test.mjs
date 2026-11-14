import { test } from 'node:test';
import assert from 'node:assert/strict';
import { auditInherited } from '../lib/prune-inherited-audit.mjs';

test('pre-deploy audit includes inactive duplicates but only the active inherited default', () => {
  const lessons = [{ id: 'l', course_id: 'c' }];
  const tables = { courses: [{ id: 'c', subarea_id: 's', cover_from: 'subarea:s' }], lessons };
  const asset = (ownerId, kind, sha256, active = true, variant = 'default') => ({ ownerId, kind, sha256, active, variant, version: 1 });
  const assets = [asset('s', 'lesson_default', 'shared'), asset('c', 'still_16x9', 'old', false),
    asset('l', 'cover_16x9', 'shared', false), asset('l', 'cover_16x9', 'old'), asset('l', 'cover_16x9', 'shared', true, 'alternate'), asset('l', 'cover_9x16', 'shared')];
  const report = auditInherited(tables, assets);
  assert.equal(report.count, 1);
  assert.equal(report.candidates[0].asset.active, false);
  assert.equal(report.candidates[0].inherited.ownerId, 's');
  assert.deepEqual(report.courseIds, ['c']);
  assert.equal(report.apply, false);
  assert.equal(report.bytesDeleted, 0);
  assert.equal(auditInherited({ courses: [{ id: 'c', subarea_id: 's' }], lessons }, assets).count, 0);
  assert.equal(auditInherited({ courses: [{ id: 'c', subarea_id: 's', cover_from: 'own' }], lessons }, [...assets, asset('c', 'lesson_default', 'own')]).count, 0);
});
