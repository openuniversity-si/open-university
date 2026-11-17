#!/usr/bin/env node
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { dirname, relative, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const sourceRoot = 'apps/web/src/';
const testFile = (file) => /\.test\.tsx?$/.test(file);
const prod = (file) => !testFile(file) && !file.includes('/testing/') && !file.startsWith(`${sourceRoot}app/(test)/`);
const walk = (dir) => existsSync(dir) ? readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name)).flatMap((entry) => {
  const path = resolve(dir, entry.name);
  return entry.isDirectory() ? walk(path) : /\.tsx?$/.test(path) ? [path] : [];
}) : [];

// A small lexer keeps comments and string contents out of the import grammar.
// Tokens retain offsets so diagnostics refer to the actual specifier, including multiline imports.
function specifiers(source) {
  const tokens = [...source.matchAll(/\/\*[\s\S]*?\*\/|\/\/[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|[\w$]+|[^\s]/g)]
    .filter(([value]) => !value.startsWith('//') && !value.startsWith('/*'));
  const result = [];
  const literal = (token) => token && /^["']/.test(token[0]);
  for (let i = 0; i < tokens.length; i++) {
    const word = tokens[i][0];
    if (word !== 'import' && word !== 'export') continue;
    const next = tokens[i + 1]?.[0];
    let target;
    if (word === 'import' && next === '(' && literal(tokens[i + 2])) target = tokens[i + 2];
    else if (word === 'import' && literal(tokens[i + 1])) target = tokens[i + 1];
    else if ((word === 'import' && next !== '.' && next !== '(') || (word === 'export' && ['{', '*', 'type'].includes(next))) {
      for (let j = i + 1; j < tokens.length && tokens[j][0] !== ';'; j++) {
        if (['import', 'export'].includes(tokens[j][0])) break;
        if (tokens[j][0] === 'from' && literal(tokens[j + 1])) { target = tokens[j + 1]; break; }
      }
    }
    if (target) result.push({ specifier: target[0].slice(1, -1), line: source.slice(0, target.index).split('\n').length });
  }
  return result;
}

export const muxTombstones = [
  'src/playback/engine/mux.ts', 'src/playback/mux-engine.tsx', 'src/playback/mux-engine.test.ts',
  'src/playback/refresh.ts', 'src/playback/actions.ts', 'src/playback/actions.test.ts',
  'src/playback/token.ts', 'src/playback/token.test.ts', 'scripts/catalog-sync-mux.ts',
  'scripts/mux-probe.ts', 'scripts/lib/mux-probe.ts', 'scripts/lib/mux-probe.test.ts',
  'scripts/lib/mux-read-only.ts', 'scripts/lib/mux-read-only.test.ts',
].map((file) => `apps/web/${file}`);
const legacy = [`${sourceRoot}catalog/load.ts`, `${sourceRoot}catalog/schema.ts`];
// Comments blanked in place, so offsets and line numbers stay those of the file.
const uncomment = (source) => source.replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, (comment) => comment.replace(/[^\n]/g, ' '));

/** The two halves (docs/architecture/FACTORY.md). The site serves releases; the factory delivers a batch through the admin API, and publication is the next step (D-053). */
export const architectureHalves = {
  site: ['site', 'catalog', 'media', 'playback', 'progress', 'identity', 'config'],
  factory: ['factory'],
};
const contextNames = [...architectureHalves.site, ...architectureHalves.factory];

export const defaultRules = [
  { id: 'L1.kernel-pure', check({ files, edges, add }) {
    for (const edge of edges) {
      if (!edge.file.startsWith(`${sourceRoot}kernel/`) || !prod(edge.file)) continue;
      const client = ['brand-ids.ts', 'slug.ts', 'errors.ts'].includes(edge.file.slice(`${sourceRoot}kernel/`.length));
      if (client || !(edge.specifier.startsWith('node:') || (edge.target?.startsWith(`${sourceRoot}kernel/`) && prod(edge.target) && files.has(edge.target)))) add(this.id, edge.file, edge.line, edge.specifier);
    }
  } },
  { id: 'L1.single-pool', check({ root, files, add }) {
    for (const file of files) {
      if (!prod(file) || file === `${sourceRoot}platform/db/pool.ts`) continue;
      const source = readFileSync(resolve(root, file), 'utf8');
      for (const match of source.matchAll(/\bnew\s+(?:pg\.)?Pool\s*\(/g)) add(this.id, file, source.slice(0, match.index).split('\n').length, 'pool construction outside platform');
    }
  } },
  { id: 'L1.logger-only', check({ root, files, add }) {
    for (const file of files) {
      if (!prod(file) || file === `${sourceRoot}platform/observability/logger.ts`) continue;
      const source = readFileSync(resolve(root, file), 'utf8');
      for (const match of source.matchAll(/\bconsole\s*\.\s*(?:log|warn|error|info|debug)\s*\(/g)) add(this.id, file, source.slice(0, match.index).split('\n').length, 'console outside logger');
    }
  } },
  { id: 'L1.platform-down', check({ edges, add }) {
    for (const edge of edges) {
      if (!prod(edge.file) || !edge.file.startsWith(`${sourceRoot}platform/`)) continue;
      if (edge.target && !(edge.target.startsWith(`${sourceRoot}kernel/`) || edge.target.startsWith(`${sourceRoot}platform/`))) add(this.id, edge.file, edge.line, edge.specifier);
    }
  } },
  // The kernel keeps the cover-kind lists and does not emit SQL. schema.ts is the only platform/db file that may name a cover owner.
  { id: 'L1.no-cover-sql', check({ root, files, add }) {
    const ownerKind = /\bowner_kind\b/;
    const coverSet = /['"]institution['"][\s\S]{0,60}['"]area['"][\s\S]{0,60}['"]subarea['"][\s\S]{0,60}['"]course['"][\s\S]{0,60}['"]lesson['"]/;
    const namedOwner = /\bowner\b[^;\n]{0,80}['"](?:course|lesson)['"]|['"](?:course|lesson)['"][^;\n]{0,40}\bowner\b/;
    for (const file of files) {
      const source = uncomment(readFileSync(resolve(root, file), 'utf8'));
      if (prod(file) && file.startsWith(`${sourceRoot}kernel/`)) {
        for (const match of source.matchAll(/\bSELECT\b|\bINSERT\b|\bpgTable\b/g)) add(this.id, file, source.slice(0, match.index).split('\n').length, 'kernel does not emit SQL');
      }
      if (!file.startsWith(`${sourceRoot}platform/db/`) || file === `${sourceRoot}platform/db/schema.ts`) continue;
      const named = ownerKind.exec(source) ?? coverSet.exec(source) ?? namedOwner.exec(source);
      if (named) add(this.id, file, source.slice(0, named.index).split('\n').length, 'platform/db does not name a cover owner');
    }
  } },
  { id: 'L1.app-error', check({ root, files, add }) {
    for (const file of files) {
      if (!prod(file) || file === `${sourceRoot}kernel/errors.ts`) continue;
      const source = readFileSync(resolve(root, file), 'utf8');
      for (const match of source.matchAll(/class\s+(\w+)\s+extends\s+Error\b/g)) {
        if (file === `${sourceRoot}catalog/server/mutation.ts` && match[1] === 'IdempotentReplay') continue;
        add(this.id, file, source.slice(0, match.index).split('\n').length, 'error outside AppError taxonomy');
      }
    }
  } },
  { id: 'L1.no-backend-to-ui', check({ edges, add }) {
    const roots = ['auth', 'identity', 'playback', 'progress', 'catalog', 'media', 'site', 'admin', 'db', 'platform', 'kernel'];
    const allowed = new Set([`${sourceRoot}catalog/domain/credits.test.ts`]);
    for (const edge of edges) {
      if (allowed.has(edge.file) || !edge.target?.startsWith(`${sourceRoot}ui/`)) continue;
      const top = edge.file.startsWith(sourceRoot) ? edge.file.slice(sourceRoot.length).split('/')[0] : '';
      if (roots.includes(top)) add(this.id, edge.file, edge.line, edge.specifier);
    }
  } },
  { id: 'L1.no-css-in-backend', check({ edges, add }) {
    for (const edge of edges) {
      if (edge.file.startsWith(`${sourceRoot}ui/`) || edge.file.startsWith(`${sourceRoot}app/`)) continue;
      if (/\.module\.css$|\.css$/.test(edge.specifier)) add(this.id, edge.file, edge.line, edge.specifier);
    }
  } },
  { id: 'L1.progress-domain-pure', check({ edges, add }) {
    for (const edge of edges) {
      if (!prod(edge.file) || !edge.file.startsWith(`${sourceRoot}progress/domain/`)) continue;
      const rules = edge.target === `${sourceRoot}progress/domain/rules.ts`;
      const kernel = edge.target?.startsWith(`${sourceRoot}kernel/`) && prod(edge.target);
      if (!rules && !kernel) add(this.id, edge.file, edge.line, edge.specifier);
    }
  } },
  { id: 'L1.catalog-no-progress-value', check({ root, edges, add }) {
    const typeOnly = (edge) => /^\s*(?:import|export)\s+type\b/.test((readFileSync(resolve(root, edge.file), 'utf8').split('\n')[edge.line - 1] ?? ''));
    for (const edge of edges) {
      if (!prod(edge.file) || !edge.file.startsWith(`${sourceRoot}catalog/domain/`)) continue;
      const progress = edge.target?.startsWith(`${sourceRoot}progress/domain/`) || edge.specifier.includes('progress/domain/');
      if (!progress || typeOnly(edge)) continue;
      add(this.id, edge.file, edge.line, 'catalog domain does not value-import progress');
    }
  } },
  { id: 'L1.shelf-boundary', check({ root, files, edges, add }) {
    const shelf = new Set([
      `${sourceRoot}catalog/domain/universities.ts`,
      `${sourceRoot}catalog/domain/countries.ts`,
      `${sourceRoot}catalog/domain/home.ts`,
      `${sourceRoot}catalog/domain/view-model.ts`,
    ]);
    const lessonHolders = ['playback/domain/', 'media/domain/', 'progress/domain/'];
    const lessonModules = ['lesson-address.ts', 'lesson-video.ts', 'text-fields.ts', 'domain/fields.ts'];
    const relOf = (file) => file.startsWith(sourceRoot) ? file.slice(sourceRoot.length) : '';
    for (const edge of edges) {
      if (!prod(edge.file) || !shelf.has(edge.target ?? '')) continue;
      const rel = relOf(edge.file);
      if (rel.startsWith('playback/') || rel.startsWith('progress/') || rel.startsWith('identity/') || rel.startsWith('factory/domain/')) {
        add(this.id, edge.file, edge.line, 'the shelf is not imported here');
      }
      if (rel.startsWith('catalog/domain/rules/') && (edge.target?.endsWith('/home.ts') || edge.target?.endsWith('/universities.ts'))) {
        add(this.id, edge.file, edge.line, 'rules do not draw the shelf');
      }
    }
    for (const edge of edges) {
      if (!prod(edge.file) || !edge.file.startsWith(`${sourceRoot}media/domain/`)) continue;
      if (edge.target?.startsWith(`${sourceRoot}catalog/`) || edge.specifier.includes('catalog/')) add(this.id, edge.file, edge.line, 'media domain does not import catalog');
    }
    for (const edge of edges) {
      if (!prod(edge.file) || !lessonHolders.some((prefix) => relOf(edge.file).startsWith(prefix))) continue;
      const names = `${edge.target ?? ''} ${edge.specifier}`;
      if (lessonModules.some((name) => names.includes(name))) add(this.id, edge.file, edge.line, 'the lesson summary is not built here');
    }
    for (const edge of edges) {
      if (!prod(edge.file) || !edge.file.startsWith(`${sourceRoot}playback/domain/`)) continue;
      const catalog = edge.target?.startsWith(`${sourceRoot}catalog/`) || edge.specifier.includes('catalog/');
      if (catalog && edge.target !== `${sourceRoot}catalog/domain/youtube-identity.ts`) add(this.id, edge.file, edge.line, 'the player imports only the video id pattern');
    }
    for (const file of files) {
      if (!prod(file) || !lessonHolders.some((prefix) => relOf(file).startsWith(prefix))) continue;
      if (uncomment(readFileSync(resolve(root, file), 'utf8')).includes('VIDEO_CHECK_FRESH_DAYS')) add(this.id, file, 1, 'the lesson summary is not built here');
    }
    const answersPath = `${sourceRoot}catalog/domain/rules/publish-answers.ts`;
    if (files.has(answersPath)) {
      const answers = uncomment(readFileSync(resolve(root, answersPath), 'utf8'));
      if ((answers.match(/owner:\s*LESSON/g) ?? []).length !== 1) add(this.id, answersPath, 1, 'the lesson has one publish answer, the video check');
      if (answers.includes('TEXT_FIELDS') || answers.includes('text-fields')) add(this.id, answersPath, 1, 'publish does not grow a field per lesson text');
      const textPath = resolve(root, `${sourceRoot}kernel/text-fields.ts`);
      if (existsSync(textPath)) {
        const text = readFileSync(textPath, 'utf8');
        const lesson = text.slice(text.indexOf('lesson:'), text.indexOf('author:'));
        for (const match of lesson.matchAll(/^\s{4}(\w+):/gm)) {
          const key = match[1] ?? '';
          if (key !== '' && new RegExp(`function\\s+\\w*${key}\\w*\\s*\\(`, 'i').test(answers)) add(this.id, answersPath, 1, `lesson text ${key} is not its own publish answer`);
        }
      }
    }
  } },
  { id: 'L1.testing-isolated', check({ files, edges, add }) {
    for (const edge of edges) if (prod(edge.file) && edge.target?.includes('/testing/')) add(this.id, edge.file, edge.line, edge.specifier);
    for (const file of files) if (file.startsWith(`${sourceRoot}app/(test)/`) && /\/(page\.tsx|route\.ts)$/.test(file)) add(this.id, file, 1, 'production route in test tree');
  } },
  { id: 'L1.mux-tombstone', check({ root, edges, toolingEdges, add }) {
    for (const file of muxTombstones) if (existsSync(resolve(root, file))) add(this.id, file, 1, 'removed module exists');
    for (const edge of [...edges, ...toolingEdges]) if (muxTombstones.includes(edge.target)) add(this.id, edge.file, edge.line, edge.specifier);
  } },
  { id: 'L1.legacy-catalog-out', check({ files, edges, add }) {
    for (const file of legacy) if (files.has(file)) add(this.id, file, 1, 'legacy module in src');
    for (const edge of edges) if (legacy.includes(edge.target) || (edge.target?.startsWith('apps/web/content/catalog/'))) add(this.id, edge.file, edge.line, edge.specifier);
  } },
  { id: 'L1.site-data-boundary', check({ edges, add }) {
    for (const edge of edges) {
      if (!edge.specifier.includes('content/site/') && !edge.target?.includes('content/site/')) continue;
      if (edge.file === `${sourceRoot}site/server/site-data.ts` || testFile(edge.file)) continue;
      add(this.id, edge.file, edge.line, edge.specifier);
    }
  } },
  { id: 'L1.no-site-pages', check({ files, add }) {
    for (const file of files) {
      if (file === `${sourceRoot}ui/Footer/copy.ts` || file.startsWith(`${sourceRoot}site/pages/`)) add(this.id, file, 1, 'institutional copy still lives in code');
    }
  } },
  { id: 'L1.client-no-site-data', check({ root, edges, add }) {
    for (const edge of edges) {
      if (!edge.target?.startsWith(`${sourceRoot}site/server/`)) continue;
      const text = readFileSync(resolve(root, edge.file), 'utf8');
      if (text.includes('"use client"') || text.includes("'use client'")) add(this.id, edge.file, edge.line, edge.specifier);
    }
  } },
  { id: 'L2.sql-owner', check({ root, files, add }) {
    const owners = { user: 'identity', session: 'identity', account: 'identity', verification: 'identity', lesson_progress: 'progress', rate_limit: 'platform', media_objects: 'media', catalog_media: 'media', course_assets: 'media', lesson_assets: 'media', subarea_assets: 'media', r2_pending_deletions: 'media', licenses: 'catalog', content_sources: 'catalog', authors: 'catalog', subject_areas: 'catalog', subject_subareas: 'catalog', courses: 'catalog', course_editions: 'catalog', lessons: 'catalog', lesson_videos: 'catalog', catalog_texts: 'catalog', home_rows: 'catalog', home_row_items: 'catalog', slug_redirects: 'catalog', catalog_releases: 'catalog', catalog_course_projections: 'catalog', catalog_release_index: 'catalog', catalog_redirects: 'catalog', catalog_audit: 'catalog', admin_idempotency: 'catalog', catalog_imports: 'catalog', catalog_home: 'catalog', catalog_ship_batches: 'catalog', catalog_ship_chunks: 'catalog', catalog_jobs: 'admin', admin_rate_limits: 'platform', config_documents: 'config', config_document_revisions: 'config' };
    const contextOf = (file) => {
      const rel = file.startsWith(sourceRoot) ? file.slice(sourceRoot.length) : '';
      if (rel.startsWith('identity/') || rel.startsWith('auth/')) return 'identity';
      if (rel.startsWith('progress/')) return 'progress';
      if (rel.startsWith('media/')) return 'media';
      if (rel.startsWith('catalog/')) return 'catalog';
      if (rel.startsWith('admin/')) return 'admin';
      if (rel.startsWith('config/')) return 'config';
      if (rel.startsWith('platform/')) return 'platform';
      return 'other';
    };
    const literals = (source) => [...source.matchAll(/`(?:\\.|[^`\\])*`|'(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*"/g)].map((match) => match[0].slice(1, -1));
    for (const file of files) {
      if (!prod(file) || !file.endsWith('.ts')) continue;
      const source = readFileSync(resolve(root, file), 'utf8');
      if (!source.includes('.query(')) continue;
      const context = contextOf(file);
      for (const raw of literals(source)) {
        let sql = raw;
        for (const hole of raw.matchAll(/\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g)) {
          const list = source.match(new RegExp(`(?:const|let|for \\(const) ${hole[1]}(?:=| of) \\[([^\\]]+)\\]`));
          const names = [...(list?.[1].matchAll(/["']([a-z0-9_]+)["']/g) ?? [])].map((item) => item[1]);
          if (names.length > 0) {
            for (const name of names) if (owners[name] && owners[name] !== context) add(this.id, file, 1, `${name} owned by ${owners[name]}`);
            sql = sql.replaceAll(hole[0], names[0]);
          } else sql = sql.replaceAll(hole[0], 'ignored');
        }
        if (!/\b(SELECT|INSERT|UPDATE|DELETE|LOCK)\b/i.test(sql)) continue;
        const tables = [...sql.matchAll(/\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+([a-z_][a-z0-9_]*)/gi)].map((item) => item[1]);
        const locked = sql.match(/\bLOCK\s+TABLE\s+([a-z0-9_,\s]+)/i);
        if (locked) tables.push(...locked[1].split(',').map((name) => name.trim().split(/\s+/)[0]).filter(Boolean));
        for (const table of tables) if (owners[table] && owners[table] !== context) add(this.id, file, 1, `${table} owned by ${owners[table]}`);
      }
    }
  } },
  { id: 'L2.media-no-catalog', check({ edges, add }) {
    for (const edge of edges) {
      if (!edge.file.startsWith(`${sourceRoot}media/`)) continue;
      const catalog = edge.target?.startsWith(`${sourceRoot}catalog/`) || edge.specifier.includes('catalog/');
      if (!catalog) continue;
      if (prod(edge.file) && edge.file.startsWith(`${sourceRoot}media/domain/`)) {
        add(this.id, edge.file, edge.line, 'media domain does not import catalog');
        continue;
      }
      if (edge.target !== `${sourceRoot}catalog/domain/cover-resolve.ts`) add(this.id, edge.file, edge.line, edge.specifier);
    }
  } },
  { id: 'L2.progress-no-catalog', check({ edges, add }) {
    for (const edge of edges) if (prod(edge.file) && edge.file.startsWith(`${sourceRoot}progress/`) && (edge.target?.startsWith(`${sourceRoot}catalog/`) || edge.specifier.includes('catalog/'))) add(this.id, edge.file, edge.line, edge.specifier);
  } },
  { id: 'L2.owner-coverage', check({ root, add }) {
    const app = ['user', 'session', 'account', 'verification', 'lesson_progress', 'rate_limit', 'media_objects', 'licenses', 'content_sources', 'authors', 'subject_areas', 'subject_subareas', 'courses', 'course_editions', 'lessons', 'lesson_videos', 'catalog_texts', 'home_rows', 'home_row_items', 'slug_redirects', 'catalog_releases', 'catalog_course_projections', 'catalog_release_index', 'catalog_redirects', 'catalog_audit', 'admin_idempotency', 'catalog_imports', 'catalog_home', 'catalog_ship_batches', 'catalog_ship_chunks', 'catalog_jobs', 'r2_pending_deletions', 'admin_rate_limits', 'catalog_media', 'config_documents', 'config_document_revisions'];
    const defined = [...readFileSync(resolve(root, `${sourceRoot}platform/db/schema.ts`), 'utf8').matchAll(/pgTable\(\s*["']([a-z0-9_]+)["']/g)].map((item) => item[1]);
    if (defined.length !== app.length || defined.some((name) => !app.includes(name)) || app.some((name) => !defined.includes(name))) add(this.id, `${sourceRoot}platform/db/schema.ts`, 1, 'app table ownership drifted');
    const tooling = readFileSync(resolve(root, 'apps/web/scripts/lib/migrations.ts'), 'utf8') + readFileSync(resolve(root, 'apps/web/tooling/migrations/0001_fidelity_reference.sql'), 'utf8');
    for (const name of ['fidelity_reference_set', 'fidelity_reference_image', 'fidelity_reference_node', 'tooling_migration']) if (!tooling.includes(name)) add(this.id, 'apps/web/scripts/lib/migrations.ts', 1, `${name} missing from tooling`);
  } },
  { id: 'L2.admin-spec-pure', check({ files, edges, add }) {
    const roots = [...files].filter((file) => file.endsWith('/admin/route-specs.ts') || file.endsWith('/admin/media-contracts.ts') || file.endsWith('/catalog-cli/routes.ts'));
    const outgoing = new Map();
    for (const edge of edges) {
      const list = outgoing.get(edge.file) ?? [];
      list.push(edge);
      outgoing.set(edge.file, list);
    }
    const seen = new Set();
    const stack = [...roots];
    while (stack.length) {
      const file = stack.pop();
      if (!file || seen.has(file)) continue;
      seen.add(file);
      for (const edge of outgoing.get(file) ?? []) {
        const specifier = edge.specifier ?? '';
        const target = edge.target ?? '';
        if (/admin\/(deps|http-dispatcher)\.ts$|media\/server\/(repository|r2|admin)\.ts$|server-only|next\/cache|(?:^|\/)pg$/.test(specifier) || /admin\/(deps|http-dispatcher)\.ts$|media\/server\/(repository|r2)\.ts$/.test(target)) add(this.id, edge.file, edge.line, specifier);
        if (edge.target) stack.push(edge.target);
      }
    }
  } },
  { id: 'L2.admin-entrypoints', check({ root, files, add }) {
    const routes = [...files].filter((file) => file.includes('/src/app/api/admin/') && file.endsWith('/route.ts'));
    if (routes.length !== 3 || !routes.some((file) => file.includes('/catalog/[...route]/route.ts')) || !routes.some((file) => file.includes('/media/[[...route]]/route.ts')) || !routes.some((file) => file.includes('/config/[...route]/route.ts'))) add(this.id, 'apps/web/src/app/api/admin', 1, `${String(routes.length)} admin entrypoints`);
    for (const file of routes) {
      const source = readFileSync(resolve(root, file), 'utf8');
      if (!source.includes('export const runtime = "nodejs"') || !source.includes('export const dynamic = "force-dynamic"')) add(this.id, file, 1, 'missing nodejs dynamic config');
      if (source.includes('authorizeAdmin') || /\bSELECT\b/.test(source)) add(this.id, file, 1, 'route file does more than delegate');
    }
  } },
  { id: 'L2.cli-api-boundary', check({ toolingEdges, add }) {
    const roots = [...new Set(toolingEdges.map((edge) => edge.file))].filter((file) => /\/catalog-cli\/(client|media-object)\.ts$|\/catalog-cli\/commands\/(media|covers)\.ts$|\/scripts\/media-(put|rollback|check)\.ts$/.test(file));
    const outgoing = new Map();
    for (const edge of toolingEdges) {
      const list = outgoing.get(edge.file) ?? [];
      list.push(edge);
      outgoing.set(edge.file, list);
    }
    const stop = new Set(['apps/web/src/media/server/storage.ts', 'apps/web/src/media/server/og.ts', 'apps/web/src/media/domain/budget.ts', 'apps/web/src/media/domain/types.ts', 'apps/web/src/catalog/domain/cover-resolve.ts', 'apps/web/scripts/lib/catalog-cli/commands/media-privileged.ts', 'apps/web/scripts/media-content-migrate.ts']);
    const banned = /media\/server\/(repository|r2|admin)\.ts$|admin\/(deps|http-dispatcher)|database-client|database-target/;
    const seen = new Set();
    const stack = [...roots];
    while (stack.length) {
      const file = stack.pop();
      if (!file || seen.has(file) || stop.has(file)) continue;
      seen.add(file);
      for (const edge of outgoing.get(file) ?? []) {
        if (banned.test(edge.specifier) || banned.test(edge.target ?? '')) add(this.id, edge.file, edge.line, edge.specifier);
        if (edge.target && !stop.has(edge.target)) stack.push(edge.target);
      }
    }
  } },
  { id: 'L2.cli-no-media-subprocess', check({ root, add }) {
    const paths = ['apps/web/scripts/lib/catalog-cli/media-object.ts', 'apps/web/scripts/lib/catalog-cli/commands/covers.ts', 'apps/web/scripts/lib/catalog-cli/commands/media.ts'];
    for (const file of paths) {
      const source = readFileSync(resolve(root, file), 'utf8');
      if (/child_process|spawn\(|execFile|mkdtemp|tmpdir|writeFile|towerMedia|deps\.run\(/.test(source)) add(this.id, file, 1, 'media flow still shells out or writes a temp file');
    }
    const wrapper = readFileSync(resolve(root, 'apps/web/tooling/tower-media'), 'utf8');
    if (wrapper.trim().split('\n').length > 10 || /curl|budget_of|case .*command/.test(wrapper)) add(this.id, 'apps/web/tooling/tower-media', 1, 'wrapper is no longer a delegation');
  } },
  { id: 'L2.single-admin-spec', check({ root, add }) {
    const scripts = walk(resolve(root, 'apps/web/scripts'));
    for (const path of scripts) {
      const source = readFileSync(path, 'utf8');
      if (source.includes('export const CLI_ROUTES = {')) add(this.id, relative(root, path), 1, 'manual CLI route table');
    }
    const media = readFileSync(resolve(root, 'apps/web/scripts/lib/catalog-cli/commands/media.ts'), 'utf8');
    const specs = readFileSync(resolve(root, 'apps/web/src/admin/route-specs.ts'), 'utf8');
    const declared = [...specs.matchAll(/spec\("media", "([A-Z]+)", "([^"]+)"/g)].map((match) => `media:${match[1]} ${match[2]}`);
    for (const match of media.matchAll(/"(media:[A-Z]+ [^"]+)"/g)) if (!declared.includes(match[1])) add(this.id, 'apps/web/scripts/lib/catalog-cli/commands/media.ts', 1, match[1]);
  } },
  { id: 'L2.admin-journal-owner', check({ root, files, add }) {
    for (const file of files) {
      if (!file.endsWith('.ts') || file.includes('/catalog/') || file.includes('/platform/db/')) continue;
      const source = readFileSync(resolve(root, file), 'utf8');
      if (source.includes('.query(') && /\b(catalog_audit|admin_idempotency)\b/.test(source)) add(this.id, file, 1, 'journal tables belong to catalog');
    }
  } },
  { id: 'L2.site-no-catalog', check({ edges, add }) {
    for (const edge of edges) {
      if (!prod(edge.file) || !edge.file.startsWith(`${sourceRoot}site/`)) continue;
      if (edge.file === `${sourceRoot}site/domain/metadata.ts` && edge.target === `${sourceRoot}catalog/domain/cover-resolve.ts`) continue;
      if (edge.target?.startsWith(`${sourceRoot}catalog/`) || edge.specifier.includes('@tower/catalog') || edge.specifier.includes('@/catalog') || edge.specifier.includes('/catalog/')) {
        add(this.id, edge.file, edge.line, edge.specifier);
      }
    }
  } },
  { id: 'L2.site-route-domain', check({ edges, files, add }) {
    const domain = new Set(['domain/route-registry.ts', 'domain/home-routing.ts', 'domain/catalog-paths.ts'].map((file) => `${sourceRoot}site/${file}`));
    for (const edge of edges) {
      if (!prod(edge.file)) continue;
      if (domain.has(edge.file) && !(edge.target?.startsWith(`${sourceRoot}site/domain/`) || edge.specifier.startsWith('./'))) {
        add(this.id, edge.file, edge.line, edge.specifier);
      }
      if (edge.file === `${sourceRoot}site/domain/metadata.ts`) {
        const allowed = edge.target?.startsWith(`${sourceRoot}site/`) || edge.target === `${sourceRoot}catalog/domain/cover-resolve.ts` || edge.specifier === 'next' || edge.specifier.startsWith('next/');
        if (!allowed) add(this.id, edge.file, edge.line, edge.specifier);
      }
      if (edge.file === `${sourceRoot}site/server/guard.ts`) {
        const allowed = edge.specifier === 'server-only' || edge.specifier === 'next/navigation' || edge.target?.startsWith(`${sourceRoot}site/domain/`);
        if (!allowed) add(this.id, edge.file, edge.line, edge.specifier);
      }
    }
    if (files.has(`${sourceRoot}site/guard.ts`) || files.has(`${sourceRoot}site/routes.ts`) || files.has(`${sourceRoot}site/home-routing.ts`)) {
      add(this.id, `${sourceRoot}site/guard.ts`, 1, 'route policy belongs in site/domain and site/server');
    }
    if (files.has(`${sourceRoot}kernel/route-registry.ts`) || files.has(`${sourceRoot}kernel/guard.ts`) || files.has(`${sourceRoot}kernel/home-routing.ts`)) {
      add(this.id, `${sourceRoot}kernel/route-registry.ts`, 1, 'routing stays out of the kernel');
    }
  } },
  { id: 'L2.public-route-projections', check({ root, files, add }) {
    const registryPath = `${sourceRoot}site/domain/route-registry.ts`;
    if (!files.has(registryPath)) return;
    const registry = readFileSync(resolve(root, registryPath), 'utf8');
    const specs = [...registry.matchAll(/id: "([^"]+)", pattern: "([^"]+)", supportsSignedInVariant: (true|false)(?:, internalPrefix: "([^"]+)")?/g)]
      .map((match) => ({ pattern: match[2], signedIn: match[3] === 'true', internalPrefix: match[4] }));
    const expected = [];
    const push = (item) => { if (item && !expected.includes(item)) expected.push(item); };
    const dynamicInternal = new Set(specs.filter((spec) => spec.pattern.includes(':') && spec.internalPrefix).map((spec) => spec.internalPrefix));
    for (const spec of specs) {
      if (!spec.signedIn || !spec.internalPrefix) continue;
      if (spec.pattern === '/') push('/');
      else if (spec.pattern.includes(':')) push(`/${spec.pattern.split('/')[1]}/:path*`);
      else push(spec.pattern);
      push(spec.internalPrefix);
      if (dynamicInternal.has(spec.internalPrefix)) push(`${spec.internalPrefix}/:path*`);
    }
    const proxy = readFileSync(resolve(root, `${sourceRoot}proxy.ts`), 'utf8');
    const matcher = [...(proxy.match(/matcher:\s*\[([\s\S]*?)\]/)?.[1] ?? '').matchAll(/"([^"]+)"/g)].map((match) => match[1]);
    if (matcher.join('|') !== expected.join('|')) add(this.id, `${sourceRoot}proxy.ts`, 1, `matcher ${matcher.join(',')} != registry ${expected.join(',')}`);
    const twins = {
      '/signed-in-home': `${sourceRoot}app/signed-in-home/page.tsx`,
      '/signed-in-c': `${sourceRoot}app/signed-in-c/[courseSlug]/(course)/page.tsx`,
    };
    const prefixes = [...new Set(specs.filter((spec) => spec.signedIn && spec.internalPrefix).map((spec) => spec.internalPrefix))];
    for (const prefix of prefixes) {
      const file = twins[prefix];
      if (!file) { add(this.id, registryPath, 1, `no twin file for ${prefix}`); continue; }
      if (!files.has(file)) add(this.id, file, 1, `missing twin for ${prefix}`);
      else {
        const source = readFileSync(resolve(root, file), 'utf8');
        if (!source.includes('force-dynamic') || !source.includes('index: false')) add(this.id, file, 1, 'signed-in twin must be dynamic and noindex');
      }
    }
    const projection = `${sourceRoot}site/domain/catalog-paths.ts`;
    if (!files.has(projection) || !readFileSync(resolve(root, projection), 'utf8').includes('PUBLIC_ROUTE_SPECS')) {
      add(this.id, projection, 1, 'ISR paths must project the route registry');
    }
  } },
  { id: 'L3.context-layout', since: '3.1', check({ files, add }) {
    const rings = new Set(['domain', 'ports', 'server', 'client', 'testing']);
    const contexts = contextNames;
    const present = new Set();
    for (const file of files) {
      for (const name of contexts) {
        const prefix = `${sourceRoot}${name}/`;
        if (!file.startsWith(prefix)) continue;
        present.add(name);
        const rest = file.slice(prefix.length);
        const ring = rest.split('/')[0];
        if (!rest.includes('/') || !rings.has(ring)) add(this.id, file, 1, 'context root must stay inside domain, ports, server, client or testing');
      }
    }
    for (const name of present) {
      for (const ring of ['domain', 'ports', 'server']) {
        const marker = `${sourceRoot}${name}/${ring}/`;
        if (![...files].some((file) => file.startsWith(marker))) add(this.id, marker, 1, 'required ring is missing');
      }
    }
  } },
  { id: 'L3.inner-pure', since: '3.1', check({ root, edges, add }) {
    const contexts = contextNames.join('|');
    const banned = /^(react|react-dom|next|server-only|better-auth|pg|drizzle-orm|sharp|@aws-sdk\/client-s3)(\/|$)|^node:(?:fs|net|http|https|child_process)(\/|$)/;
    for (const edge of edges) {
      if (!prod(edge.file)) continue;
      const match = new RegExp(`^${sourceRoot}(${contexts})/(domain|ports)/`).exec(edge.file);
      if (!match) continue;
      if (edge.target && /\/(server|client|testing)\//.test(edge.target)) add(this.id, edge.file, edge.line, edge.specifier);
      const line = readFileSync(resolve(root, edge.file), 'utf8').split('\n')[edge.line - 1] ?? '';
      const typeOnly = /^\s*import\s+type\b/.test(line);
      const databaseType = /^(?:pg|drizzle-orm)(?:\/|$)/.test(edge.specifier) || edge.target?.startsWith(`${sourceRoot}platform/db/`) || /platform\/db(?:\/|$)/.test(edge.specifier);
      const jsonImport = edge.specifier.endsWith('.json') || edge.target?.endsWith('.json');
      const platformImport = edge.target?.startsWith(`${sourceRoot}platform/`) || /(?:^|\/)platform\//.test(edge.specifier);
      // ADR-27 registers this JSON as the domain copy. The title string is not allowed in any other file.
      const registeredConfig = edge.file === `${sourceRoot}catalog/domain/config/index.ts` && edge.specifier.endsWith('values.json');
      if (match[2] === 'domain' && ((jsonImport && !registeredConfig) || platformImport)) add(this.id, edge.file, edge.line, edge.specifier);
      else if (typeOnly && (databaseType || edge.specifier === 'next' || edge.specifier.startsWith('next/'))) add(this.id, edge.file, edge.line, edge.specifier);
      if (typeOnly) continue;
      if (banned.test(edge.specifier) || edge.specifier.startsWith('next/')) add(this.id, edge.file, edge.line, edge.specifier);
    }
    for (const name of contexts.split('|')) {
      for (const ring of ['domain', 'ports']) {
        const dir = resolve(root, `${sourceRoot}${name}/${ring}`);
        for (const path of walk(dir)) {
          const file = relative(root, path);
          if (!prod(file)) continue;
          const source = readFileSync(path, 'utf8').replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, '');
          if (/\bprocess\.env\b|\bwindow\b|\bdocument\b|\blocalStorage\b|\bsessionStorage\b|\bfetch\s*\(/.test(source)) {
            add(this.id, file, 1, 'domain or port reaches env, DOM, storage or fetch');
          }
        }
      }
    }
  } },
  { id: 'L3.provider-boundary', since: '3.1', check({ edges, add }) {
    for (const edge of edges) {
      if (!prod(edge.file)) continue;
      if (edge.specifier.startsWith('better-auth') && !edge.file.startsWith(`${sourceRoot}identity/server/`)) add(this.id, edge.file, edge.line, edge.specifier);
      if (edge.target?.endsWith('playback/client/youtube-engine.ts') && !edge.file.startsWith(`${sourceRoot}playback/client/`)) add(this.id, edge.file, edge.line, edge.specifier);
    }
  } },
  { id: 'L3.source-registry', since: '3.1', check({ root, files, edges, add }) {
    const owner = `${sourceRoot}catalog/domain/youtube-identity.ts`;
    const driver = `${sourceRoot}playback/domain/drivers/youtube.ts`;
    const registry = `${sourceRoot}playback/server/source-registry.ts`;
    if (!files.has(owner) || !files.has(driver) || !files.has(registry)) { add(this.id, registry, 1, 'lesson video identity, youtube driver or source registry is missing'); return; }
    const pattern = /\[A-Za-z0-9_-\]\{11\}/;
    if (!pattern.test(readFileSync(resolve(root, owner), 'utf8'))) add(this.id, owner, 1, 'youtube id pattern must live on the lesson');
    const driverText = readFileSync(resolve(root, driver), 'utf8');
    if (!driverText.includes('youtubeIdSchema') || !driverText.includes('catalog/domain/youtube-identity')) add(this.id, driver, 1, 'the player imports the lesson video id');
    if (pattern.test(driverText)) add(this.id, driver, 1, 'youtube id pattern is copied in the player');
    for (const file of files) {
      if (!prod(file) || file === owner || file === driver) continue;
      const inCatalog = file.startsWith(`${sourceRoot}catalog/`);
      const inPlayback = file.startsWith(`${sourceRoot}playback/`);
      if (!inCatalog && !inPlayback) continue;
      if (pattern.test(readFileSync(resolve(root, file), 'utf8'))) add(this.id, file, 1, 'youtube id pattern is copied outside the lesson');
    }
    for (const edge of edges) {
      if (!prod(edge.file) || !edge.file.startsWith(`${sourceRoot}catalog/domain/`)) continue;
      const where = `${edge.target ?? ''} ${edge.specifier}`;
      if (where.includes('playback/domain/drivers/youtube')) add(this.id, edge.file, edge.line, 'catalog domain does not import the youtube driver');
    }
    const text = readFileSync(resolve(root, registry), 'utf8');
    if (!text.includes('youtubeSourceDriver') || !text.includes('institutionalUrlDriver')) add(this.id, registry, 1, 'registry must compose both drivers');
  } },
  { id: 'L3.media-key-bridge', since: '3.2', check({ files, add }) {
    const types = `${sourceRoot}media/domain/types.ts`;
    const objects = `${sourceRoot}media/domain/objects.ts`;
    if (!files.has(types) || !files.has(objects)) add(this.id, objects, 1, 'media key producers must live in the media domain');
  } },
  { id: 'L3.no-retired-paths', since: '3.2', check({ root, files, edges, add }) {
    const retired = /catalog\/admin\/|@\/media\/(?:types|objects|storage|repository|index|group|inheritance|og)(?:\.ts)?["']|@\/site\/(?:hosts|origin|indexing|build-info)(?:\.ts)?["']|@\/catalog\/(?:read|queries|release|tables|invalidate)(?:\.ts)?["']/;
    for (const edge of edges) if (retired.test(edge.specifier) || retired.test(`${edge.specifier}"`)) add(this.id, edge.file, edge.line, edge.specifier);
    // D-029. The doctor is the runtime proof that these relations are gone, so it may name them.
    const listed = 'retired media path: course_assets, lesson_assets, subarea_assets, authors.media_sha256, home_rows.media_sha256, home_rows.og_media_sha256';
    const names = /\b(?:course_assets|lesson_assets|subarea_assets)\b|\bog_media_sha256\b|authors\.media_sha256|home_rows\.media_sha256/;
    const exempt = new Set([`${sourceRoot}catalog/server/doctor.ts`]);
    const scan = (file) => {
      if (exempt.has(file) || file.endsWith('.test.ts')) return;
      const source = uncomment(readFileSync(resolve(root, file), 'utf8'));
      const match = names.exec(source);
      if (match) add(this.id, file, source.slice(0, match.index).split('\n').length, listed);
    };
    for (const file of files) scan(file);
    for (const path of walk(resolve(root, 'apps/web/scripts'))) scan(relative(root, path));
  } },
  { id: 'L3.contract-coverage', since: '3.3', check({ root, files, add }) {
    const reservedFiles = [
      ['4.2', `${sourceRoot}catalog/testing/in-memory-queries.ts`],
      ['4.3', `${sourceRoot}playback/testing/fake-oembed.ts`],
      ['4.4', `${sourceRoot}admin/testing/in-memory-jobs.ts`],
    ];
    const reservedIds = new Set(['CatalogQueriesPort', 'OEmbedResolverPort', 'JobStorePort']);
    const applied = new Set(LAYER_ORDER);
    for (const [since, file] of reservedFiles) {
      if (files.has(file) && !applied.has(since)) add(this.id, file, 1, `adapter exists before state ${since}`);
    }
    const needed = /(?:Port|Store|Transport|Engine|Driver|Database|Lookup)$/;
    const infra = new Set(['UnitOfWork', 'Queryable', 'PooledClient', 'DbPool']);
    const discovered = [];
    const scanned = [...files].filter((file) => /\/ports\/[^/]+\.ts$/.test(file) || file === `${sourceRoot}platform/db/uow.ts` || file === `${sourceRoot}progress/server/repo.ts`);
    for (const file of scanned) {
      const source = readFileSync(resolve(root, file), 'utf8');
      for (const match of source.matchAll(/export interface (\w+)/g)) {
        if (needed.test(match[1]) || infra.has(match[1])) discovered.push(match[1]);
      }
    }
    if (discovered.length === 0) return;
    const registryPath = 'apps/web/tooling/architecture-contracts.json';
    if (!existsSync(resolve(root, registryPath))) { add(this.id, registryPath, 1, 'contract registry is missing'); return; }
    const registry = JSON.parse(readFileSync(resolve(root, registryPath), 'utf8'));
    const entries = new Map((registry.ports ?? []).map((entry) => [entry.id, entry]));
    for (const id of reservedIds) if (entries.has(id) && !applied.has(entries.get(id).since)) add(this.id, registryPath, 1, `${id} is registered before ${entries.get(id).since}`);
    for (const name of discovered) {
      const entry = entries.get(name);
      if (!entry) { add(this.id, registryPath, 1, `${name} has no contract entry`); continue; }
      if (!applied.has(entry.since)) add(this.id, registryPath, 1, `${name} since ${entry.since} is not applied`);
      const contract = entry.contract;
      if (entry.kind === 'port' && !contract?.cases?.length) add(this.id, registryPath, 1, `${name} has no cases`);
      if (contract?.cases?.length) {
        if (!existsSync(resolve(root, contract.file))) add(this.id, contract.file, 1, 'contract file is missing');
        else {
          const body = readFileSync(resolve(root, contract.file), 'utf8');
          for (const id of contract.cases) if (!body.includes(id)) add(this.id, contract.file, 1, `case ${id} is missing`);
        }
      }
      if (entry.kind === 'port' && !entry.memory?.file) add(this.id, registryPath, 1, `${name} memory adapter is missing`);
      if (entry.memory?.file && (!existsSync(resolve(root, entry.memory.file)) || !readFileSync(resolve(root, entry.memory.file), 'utf8').includes(entry.memory.symbol))) {
        add(this.id, entry.memory.file, 1, `${name} memory adapter is missing`);
      }
      for (const real of entry.real ?? []) {
        if (!existsSync(resolve(root, real.file)) || !readFileSync(resolve(root, real.file), 'utf8').includes(real.symbol)) add(this.id, real.file, 1, `${name} real adapter ${real.symbol} is missing`);
      }
    }
    const intFile = 'apps/web/test/int/executable-contracts.int.test.ts';
    const intText = existsSync(resolve(root, intFile)) ? readFileSync(resolve(root, intFile), 'utf8') : '';
    for (const id of registry.integrationOnly ?? []) if (!intText.includes(id)) add(this.id, intFile, 1, `integration case ${id} is not identified`);
  } },
  { id: 'L3.testing-no-io', since: '3.3', check({ root, files, edges, add }) {
    const targets = [...files].filter((file) => !file.endsWith('.test.ts') && (/\/testing\/in-memory-[^/]+\.ts$/.test(file) || /\/testing\/[^/]*contract\.ts$/.test(file)));
    const banned = /^(?:pg|sharp|better-auth|server-only)(?:\/|$)|^@aws-sdk\/|^node:(?:fs|net|http|https|child_process)(?:\/|$)/;
    const typeOnly = (edge) => /^\s*(?:import|export)\s+type\b/.test((readFileSync(resolve(root, edge.file), 'utf8').split('\n')[edge.line - 1] ?? ''));
    for (const start of targets) {
      const seen = new Set([start]);
      const queue = [start];
      while (queue.length) {
        const file = queue.pop();
        for (const edge of edges) {
          if (edge.file !== file || typeOnly(edge)) continue;
          if (banned.test(edge.specifier) || edge.target?.includes('/server/')) add(this.id, edge.file, edge.line, edge.specifier);
          if (start.includes('contract.ts') && (edge.specifier.includes('in-memory-') || edge.target?.includes('in-memory-'))) add(this.id, edge.file, edge.line, edge.specifier);
          if (edge.target?.startsWith(sourceRoot) && files.has(edge.target) && !seen.has(edge.target)) { seen.add(edge.target); queue.push(edge.target); }
        }
      }
      if (!start.includes('in-memory-')) continue;
      const source = readFileSync(resolve(root, start), 'utf8').replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, '');
      if (/\bprocess\.env\b|\bDate\.now\b|\bMath\.random\b|\bfetch\s*\(/.test(source)) add(this.id, start, 1, 'memory adapter reads the clock, the environment or the network');
    }
  } },
  { id: 'L4.projection-boundary', since: '4.1', check({ root, files, edges, add }) {
    const domain = `${sourceRoot}catalog/domain/`;
    for (const edge of edges) {
      if (!edge.file.startsWith(domain)) continue;
      if (edge.specifier.includes('projections-repo') || edge.target?.includes('projections-repo')) add(this.id, edge.file, edge.line, edge.specifier);
    }
    const tables = /catalog_course_projections|catalog_release_index|catalog_redirects/;
    for (const file of files) {
      if (!file.endsWith('.ts') && !file.endsWith('.sql')) continue;
      if (file.startsWith(`${sourceRoot}catalog/server/`)) continue;
      if (file === `${sourceRoot}platform/db/schema.ts`) continue;
      if (file.startsWith('apps/web/drizzle/')) continue;
      if (file.includes('.test.') || file.includes('.int.test.')) continue;
      const source = readFileSync(resolve(root, file), 'utf8');
      if (tables.test(source)) add(this.id, file, 1, 'projection tables are owned by the catalog server');
    }
  } },
  { id: 'L4.bundle-boundary', since: '4.3', check({ edges, add }) {
    for (const edge of edges) {
      const domain = edge.file.endsWith('catalog/domain/bundle.ts');
      const apply = edge.file.endsWith('catalog/server/bundle-apply.ts');
      const cli = edge.file.includes('catalog-cli/commands/bundle.ts');
      if (domain && (edge.specifier.includes('/server/') || edge.specifier.includes('uow') || edge.specifier.includes('node:fs') || edge.specifier === 'pg')) add(this.id, edge.file, edge.line, edge.specifier);
      if (apply && (edge.specifier.includes('googleapis') || edge.specifier.includes('youtube-sdk'))) add(this.id, edge.file, edge.line, edge.specifier);
      if (cli && (edge.specifier.includes('uow') || edge.specifier.includes('/platform/db/') || edge.specifier.includes('storage'))) add(this.id, edge.file, edge.line, edge.specifier);
    }
  } },
  { id: 'L4.job-boundary', since: '4.4', check({ root, files, edges, toolingEdges, add }) {
    for (const edge of [...edges, ...toolingEdges]) {
      if (edge.file.endsWith('admin/ports/jobs.ts') && (edge.specifier === 'pg' || edge.specifier.includes('uow') || edge.specifier.includes('/platform/db/'))) add(this.id, edge.file, edge.line, edge.specifier);
      if (edge.file.includes('catalog-cli/commands/ship.ts') && (edge.specifier.includes('jobs-repo') || edge.specifier === 'pg' || edge.specifier.includes('uow') || edge.specifier.includes('storage'))) add(this.id, edge.file, edge.line, edge.specifier);
    }
    const table = /catalog_jobs/;
    for (const file of files) {
      if (!file.endsWith('.ts') && !file.endsWith('.sql')) continue;
      if (file.endsWith('admin/server/jobs-repo.ts') || file === `${sourceRoot}platform/db/schema.ts` || file.startsWith('apps/web/drizzle/')) continue;
      if (file.includes('.test.') || file.includes('.int.test.')) continue;
      if (table.test(readFileSync(resolve(root, file), 'utf8'))) add(this.id, file, 1, 'catalog_jobs is owned by the admin jobs adapter');
    }
    for (const file of files) {
      if (!file.endsWith('admin/route-specs.ts')) continue;
      const source = readFileSync(resolve(root, file), 'utf8');
      const mutable = /spec\("[^"]+", "[A-Z]+", "[^"]+", "[^"]+", "[a-z.]+"/.test(source);
      if (mutable && !source.includes('permission')) add(this.id, file, 1, 'mutable admin spec has no permission');
    }
  } },
  { id: 'L5.lifecycle', since: '5.4', check({ root, files, edges, toolingEdges, add }) {
    for (const edge of [...edges, ...toolingEdges]) {
      if (edge.file.endsWith('admin/lifecycle.ts') && (edge.specifier.includes('media/server') || edge.specifier === 'pg' || edge.specifier.includes('uow') || edge.specifier.includes('storage'))) add(this.id, edge.file, edge.line, edge.specifier);
      if (edge.file.includes('catalog-cli/commands/lifecycle.ts') && (edge.specifier.includes('uow') || edge.specifier === 'pg' || edge.specifier.includes('jobs-repo') || edge.specifier.includes('storage'))) add(this.id, edge.file, edge.line, edge.specifier);
    }
    const marker = /orphaned_at/;
    for (const file of files) {
      if (!file.endsWith('.ts') && !file.endsWith('.sql')) continue;
      if (file.endsWith('media/server/lifecycle.ts') || file === `${sourceRoot}platform/db/schema.ts` || file.startsWith('apps/web/drizzle/')) continue;
      if (file.includes('.test.') || file.includes('.int.test.')) continue;
      if (marker.test(readFileSync(resolve(root, file), 'utf8'))) add(this.id, file, 1, 'orphaned_at is owned by the media lifecycle adapter');
    }
  } },
  { id: 'L5.cycles', since: '5.3', check({ files, edges, add }) {
    const cycles = stronglyConnected(files, edges);
    if (cycles > 0) add(this.id, `${sourceRoot}kernel/env.ts`, 1, `${String(cycles)} non-trivial import cycles`);
  } },
  { id: 'L5.env', since: '5.2', check({ root, files, edges, add }) {
    const facade = `${sourceRoot}kernel/env.ts`;
    const strip = (source) => source.replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, '');
    const readsEnv = (source) => /process\s*(?:\.\s*env|\[\s*["']env["']\s*\])/.test(strip(source));
    for (const file of files) {
      if (!prod(file) || !file.endsWith('.ts') && !file.endsWith('.tsx')) continue;
      if (file === facade) continue;
      if (readsEnv(readFileSync(resolve(root, file), 'utf8'))) add(this.id, file, 1, 'process env is read outside the kernel facade');
    }
    const closure = new Set();
    const pending = [...files].filter((file) => prod(file) && (file.includes('/ui/') || strip(readFileSync(resolve(root, file), 'utf8')).includes('"use client"')));
    for (const file of pending) closure.add(file);
    for (const file of closure) {
      for (const edge of edges) {
        if (edge.file !== file || !edge.target || !files.has(edge.target) || !prod(edge.target)) continue;
        if (!closure.has(edge.target)) { closure.add(edge.target); }
      }
    }
    let grew = true;
    while (grew) {
      grew = false;
      for (const edge of edges) {
        if (!closure.has(edge.file) || !edge.target || !prod(edge.target) || closure.has(edge.target)) continue;
        closure.add(edge.target);
        grew = true;
      }
    }
    for (const edge of edges) if (edge.target === facade && closure.has(edge.file)) add(this.id, edge.file, edge.line, edge.specifier);
    const health = `${sourceRoot}app/api/health/route.ts`;
    for (const edge of edges) {
      if (edge.file !== health) continue;
      if (edge.specifier === 'pg' || edge.specifier.includes('pool') || edge.specifier.includes('projections-repo')) add(this.id, edge.file, edge.line, edge.specifier);
    }
  } },
  { id: 'L5.media-queries', since: '5.1', check({ root, files, edges, add }) {
    const projection = /SELECT\s+ext\s+FROM\s+media_objects/i;
    const tableLock = /LOCK\s+TABLE/i;
    for (const file of files) {
      if (!file.startsWith(`${sourceRoot}media/`) || file.includes('.test.')) continue;
      const source = readFileSync(resolve(root, file), 'utf8');
      if (projection.test(source) || tableLock.test(source)) add(this.id, file, 1, 'media queries use a join and advisory locks');
    }
    const owners = `${sourceRoot}catalog/server/media-owners.ts`;
    if (files.has(owners) && tableLock.test(readFileSync(resolve(root, owners), 'utf8'))) add(this.id, owners, 1, 'catalog media owners use advisory locks');
    for (const edge of edges) {
      if (edge.file.endsWith('media/server/r2-bulk.ts') && edge.specifier.includes('migrate-dns')) add(this.id, edge.file, edge.line, edge.specifier);
    }
  } },
  { id: 'L6.single-cover-resolver', check({ root, files, add }) {
    const resolver = `${sourceRoot}catalog/domain/cover-resolve.ts`;
    for (const file of files) {
      if (!prod(file) || file === resolver) continue;
      const source = uncomment(readFileSync(resolve(root, file), 'utf8'));
      for (const match of source.matchAll(/\b(?:function\s+resolveCover\b|(?:const|let)\s+resolveCover\s*=)/g)) {
        add(this.id, file, source.slice(0, match.index).split('\n').length, 'cover decisions belong to catalog/domain/cover-resolve.ts');
      }
      if (file.startsWith(`${sourceRoot}media/server/`)) continue;
      for (const match of source.matchAll(/\b(?:FROM|JOIN)\s+"?(?:catalog_media|course_assets|lesson_assets|subarea_assets)\b/gi)) {
        add(this.id, file, source.slice(0, match.index).split('\n').length, 'cover rows are read only by the media adapter');
      }
    }
  } },
  // INV-R2: catalog rules live in src/catalog/domain/rules/, each id declared once (S04, STRUCTURE.md B4).
  { id: 'L6.rules-in-core', check({ root, files, add }) {
    const core = `${sourceRoot}catalog/domain/rules/`;
    for (const file of files) {
      if (!prod(file) || file.startsWith(core)) continue;
      const source = uncomment(readFileSync(resolve(root, file), 'utf8'));
      const line = (index) => source.slice(0, index).split('\n').length;
      for (const match of source.matchAll(/\bdeclareRule\s*\(/g)) add(this.id, file, line(match.index), 'rule declared outside the rules core');
      if (!file.startsWith(`${sourceRoot}catalog/server/`)) continue;
      for (const match of source.matchAll(/\brule\s*:\s*["'`]/g)) add(this.id, file, line(match.index), 'rule message built in server');
    }
  } },
  { id: 'L6.single-rule', check({ root, files, add }) {
    const declared = new Map();
    for (const file of [...files].sort()) {
      if (!prod(file)) continue;
      const source = uncomment(readFileSync(resolve(root, file), 'utf8'));
      for (const match of source.matchAll(/\bdeclareRule\s*\(\s*["'`]([^"'`]+)["'`]/g)) {
        const first = declared.get(match[1]);
        if (first) add(this.id, file, source.slice(0, match.index).split('\n').length, `rule ${match[1]} is already declared in ${first}`);
        else declared.set(match[1], file);
      }
    }
  } },
  // D-053 / D-005 / INV-R4: the factory delivers the batch through the admin API and never opens the database.
  { id: 'L6.factory-api-only', check({ edges, toolingEdges, add }) {
    const factoryFile = (file) => file.startsWith(`${sourceRoot}factory/`) || file.includes('/scripts/tower-factory') || file.includes('/scripts/lib/factory-');
    const database = (value) => /platform\/db|(?:^|\/)pg(?:\/|$)|drizzle-orm/.test(value);
    for (const edge of [...edges, ...toolingEdges]) {
      if (!factoryFile(edge.file)) continue;
      if (database(edge.specifier) || database(edge.target ?? '')) add(this.id, edge.file, edge.line, 'the factory delivers the batch through the admin API and never imports the database');
    }
  } },
  { id: 'L4.query-consumers', since: '4.2', check({ edges, add }) {
    for (const edge of edges) {
      if (!edge.file.startsWith(`${sourceRoot}app/`) || edge.file === `${sourceRoot}app/api/health/route.ts`) continue;
      const fullCatalog = edge.specifier === '@tower/catalog' || edge.target?.includes('/catalog/server/read');
      const repository = edge.specifier.includes('projections-repo') || edge.specifier.includes('table-io') || edge.target?.includes('/catalog/server/projections-repo') || edge.target?.includes('/catalog/server/table-io');
      const pool = edge.specifier === 'pg' || edge.specifier.startsWith('pg/') || edge.specifier.includes('platform/db') || edge.target?.includes('/platform/db/');
      if (fullCatalog || repository || pool) add(this.id, edge.file, edge.line, edge.specifier);
    }
  } },
  { id: 'L7.cache-no-sql', check({ root, files, edges, add }) {
    const nextOrReact = (specifier) => specifier === 'react' || specifier.startsWith('react/') || specifier === 'react-dom' || specifier.startsWith('react-dom/') || specifier === 'next' || specifier.startsWith('next/');
    const cached = new Set();
    for (const edge of edges) {
      if (!prod(edge.file) || !edge.file.includes('/server/')) continue;
      if (nextOrReact(edge.specifier)) cached.add(edge.file);
    }
    for (const file of cached) {
      if (!files.has(file)) continue;
      const source = readFileSync(resolve(root, file), 'utf8');
      const at = source.indexOf('.query(');
      if (at < 0) continue;
      add(this.id, file, source.slice(0, at).split('\n').length, '.query(');
    }
    for (const edge of edges) {
      if (!prod(edge.file) || edge.specifier !== 'next/headers') continue;
      if (edge.file.startsWith(`${sourceRoot}app/`)) continue;
      add(this.id, edge.file, edge.line, 'next/headers');
    }
  } },
  { id: 'L7.catalog-http-ports', check({ edges, add }) {
    for (const edge of edges) {
      if (edge.file !== `${sourceRoot}catalog/server/http.ts`) continue;
      const where = `${edge.target ?? ''} ${edge.specifier}`;
      if (where.includes('media/server/') || where.includes('playback/server/')) add(this.id, edge.file, edge.line, edge.specifier);
    }
  } },
  { id: 'L7.handler-no-sql', check({ root, files, add }) {
    const handlers = [
      `${sourceRoot}catalog/server/ship-batch.ts`,
      `${sourceRoot}catalog/server/courses.ts`,
      `${sourceRoot}catalog/server/lessons.ts`,
      `${sourceRoot}catalog/server/authors.ts`,
      `${sourceRoot}catalog/server/texts.ts`,
      `${sourceRoot}catalog/server/home.ts`,
      `${sourceRoot}catalog/server/deletion.ts`,
      `${sourceRoot}catalog/server/bundle-apply.ts`,
      `${sourceRoot}catalog/server/batch-apply.ts`,
      `${sourceRoot}catalog/server/doctor.ts`,
      `${sourceRoot}catalog/server/list-projection.ts`,
      `${sourceRoot}catalog/server/cover-kinds.ts`,
    ];
    for (const file of handlers) {
      if (!files.has(file)) continue;
      const source = readFileSync(resolve(root, file), 'utf8');
      const at = source.indexOf('.query(');
      if (at < 0) continue;
      add(this.id, file, source.slice(0, at).split('\n').length, '.query(');
    }
  } },
  { id: 'L7.catalog-no-media-server', check({ edges, add }) {
    const listed = new Set([
      `${sourceRoot}catalog/server/read.ts`,
      `${sourceRoot}catalog/server/authors.ts`,
      `${sourceRoot}catalog/server/batch-apply.ts`,
      `${sourceRoot}catalog/server/media.ts`,
      `${sourceRoot}catalog/server/reference.ts`,
      `${sourceRoot}catalog/server/courses.ts`,
      `${sourceRoot}catalog/server/cover-kinds.ts`,
      `${sourceRoot}catalog/server/deletion.ts`,
      `${sourceRoot}catalog/server/doctor.ts`,
      `${sourceRoot}catalog/server/home.ts`,
    ]);
    for (const edge of edges) {
      if (!listed.has(edge.file)) continue;
      const where = `${edge.target ?? ''} ${edge.specifier}`;
      if (where.includes('media/server/')) add(this.id, edge.file, edge.line, edge.specifier);
    }
  } },
  { id: 'L7.one-store', check({ edges, add }) {
    const server = `${sourceRoot}media/server/`;
    const provider = (specifier) => ['aws4fetch', 'sharp', 'node:fs'].find((name) => specifier === name || specifier.startsWith(`${name}/`));
    const seen = new Map();
    for (const edge of edges) {
      if (!prod(edge.file) || !edge.file.startsWith(server)) continue;
      const family = provider(edge.specifier);
      if (!family) continue;
      if (edge.file === `${server}storage.ts`) { add(this.id, edge.file, edge.line, edge.specifier); continue; }
      const families = seen.get(edge.file) ?? new Set();
      if (families.size && !families.has(family)) add(this.id, edge.file, edge.line, 'imports more than one media provider');
      families.add(family);
      seen.set(edge.file, families);
    }
  } },
  { id: 'L7.identity-domain', check({ edges, add }) {
    for (const edge of edges) {
      if (!prod(edge.file) || !edge.file.startsWith(`${sourceRoot}identity/domain/`)) continue;
      const site = edge.target?.startsWith(`${sourceRoot}site/`) || /(^|\/)site\//.test(edge.specifier);
      if (site) add(this.id, edge.file, edge.line, 'identity domain does not import site');
    }
  } },
];

const LAYER_ORDER = ['1.1', '1.2', '1.3', '1.4', '2.1', '2.2', '2.3', '2.4', '3.1', '3.2', '3.3', '4.1', '4.2', '4.3', '4.4', '5.1', '5.2', '5.3', '5.4'];

/** @param {{root?: string, rules?: typeof defaultRules}} options */
export function rulesThrough(through) {
  if (!through) return defaultRules;
  const limit = LAYER_ORDER.indexOf(through);
  if (limit < 0) throw new Error(`Unknown architecture layer ${through}`);
  return defaultRules.filter((rule) => LAYER_ORDER.indexOf(rule.since ?? '1.1') <= limit);
}

export function stronglyConnected(files, edges) {
  const index = new Map();
  const low = new Map();
  const stack = [];
  const onStack = new Set();
  let current = 0;
  let nontrivial = 0;
  const adjacent = new Map([...files].map((file) => [file, []]));
  for (const edge of edges) {
    if (!adjacent.has(edge.file) || !edge.target || !adjacent.has(edge.target) || edge.target === undefined) continue;
    adjacent.get(edge.file).push(edge.target);
    if (edge.file === edge.target) nontrivial += 1;
  }
  function visit(node) {
    index.set(node, current);
    low.set(node, current);
    current += 1;
    stack.push(node);
    onStack.add(node);
    for (const next of adjacent.get(node) ?? []) {
      if (!index.has(next)) { visit(next); low.set(node, Math.min(low.get(node), low.get(next))); }
      else if (onStack.has(next)) low.set(node, Math.min(low.get(node), index.get(next)));
    }
    if (low.get(node) === index.get(node)) {
      const component = [];
      let member;
      do {
        member = stack.pop();
        onStack.delete(member);
        component.push(member);
      } while (member !== node);
      if (component.length > 1) nontrivial += 1;
    }
  }
  for (const file of files) if (!index.has(file)) visit(file);
  return nontrivial;
}

export function architectureReport(options = {}) {
  const violations = checkArchitecture(options);
  return { through: options.through ?? LAYER_ORDER.at(-1), ...lastGraph, violations };
}

// The root holds apps/web; every rule reads files under apps/web only.
export function checkArchitecture({ root = resolve(dirname(fileURLToPath(import.meta.url)), '../../..'), rules, through } = {}) {
  rules ??= through ? rulesThrough(through) : defaultRules;
  root = resolve(root);
  const paths = walk(resolve(root, sourceRoot));
  const files = new Set(paths.map((path) => relative(root, path)));
  const aliases = { '@tower/catalog': `${sourceRoot}catalog/read.ts`, '@tower/media': `${sourceRoot}media/index.ts`, '@tower/playback-engine': `${sourceRoot}playback/client/youtube.ts` };
  const resolveTarget = (file, specifier) => {
    let target = aliases[specifier];
    if (!target && specifier.startsWith('@/')) target = `${sourceRoot}${specifier.slice(2)}`;
    if (!target && specifier.startsWith('.')) target = relative(root, resolve(root, dirname(file), specifier));
    if (!target) return undefined;
    target = relative(root, resolve(root, target));
    if (/\.(ts|tsx|json)$/.test(target)) return target;
    return [target, `${target}.ts`, `${target}.tsx`, `${target}/index.ts`, `${target}/index.tsx`].find((path) => files.has(path) || muxTombstones.includes(path)) ?? `${target}.ts`;
  };
  const readEdges = (paths) => paths.flatMap((path) => {
    const file = relative(root, path);
    return specifiers(readFileSync(path, 'utf8')).map((entry) => ({ file, ...entry, target: resolveTarget(file, entry.specifier) }));
  });
  const edges = readEdges(paths);
  const toolingEdges = readEdges(walk(resolve(root, 'apps/web/scripts')));
  const violations = [];
  const add = (rule, file, line, detail) => violations.push({ rule, file, line, detail });
  for (const rule of rules) rule.check({ root, files, edges, toolingEdges, add });
  lastGraph = { nodeCount: files.size, edgeCount: edges.length, cyclicSccCount: stronglyConnected(files, edges.filter((edge) => edge.file !== edge.target)) };
  return violations.sort((a, b) => a.file.localeCompare(b.file) || a.line - b.line || a.rule.localeCompare(b.rule));
}

let lastGraph = { nodeCount: 0, edgeCount: 0, cyclicSccCount: 0 };

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const start = performance.now();
  const throughIndex = process.argv.indexOf('--through');
  const through = throughIndex >= 0 ? process.argv[throughIndex + 1] : undefined;
  const violations = checkArchitecture({ through });
  for (const v of violations) console.error(`${v.file}:${v.line} ${v.rule}: ${v.detail}`);
  console.log(`Architecture: ${violations.length} violation(s), ${Math.round(performance.now() - start)} ms`);
  process.exitCode = violations.length ? 1 : 0;
}
