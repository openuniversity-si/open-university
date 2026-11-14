// VAZÃO F37 (D-299): the gate's verdict as an Origin check run, posted here because only the Worker holds the Origin
// app's signing key. Origin refuses a check run from a user principal (scope repository:checks:write is integration
// only), so the engine sends the check-run body it built (forge_origin_client.check_run_body) to POST /v1/check-run with
// the events token, and this route:
//   1. signs an app JWT the way the origin CLI does (src/actions/app/webhook/app-jwt.ts): header {alg: EdDSA, typ: JWT},
//      claims {iss: app id, aud: origin-apps, iat, exp: iat + 300}, Ed25519 over `header.payload`, base64url;
//   2. exchanges it for an installation token (oit_..., at most 15 minutes) at
//      POST /v1/origin/app/installations/{id}/access_tokens, kept in this isolate until a minute before it ends;
//   3. posts {headSha, checkSuite, checkRun} to POST /v1/origin/repos/{owner}/{name}/check-runs, for REPO only.
// Off until the Torre sets ORIGIN_APP_PRIVATE_KEY (secret: the app's Ed25519 PKCS#8 PEM, whose public half is added with
// `origin app key add`), ORIGIN_APP_ID and ORIGIN_APP_INSTALLATION_ID: without them the route answers 503 'not
// configured'. The token answer's field names are not in the public spec we hold; `token`, `accessToken` and
// `access_token` are read, and `expiresAt`/`expires_at` when present.

export const ORIGIN_API = 'https://api.cursor.com/v1/origin';
export const APP_AUDIENCE = 'origin-apps';
export const APP_JWT_TTL_S = 300;
export const TOKEN_MARGIN_MS = 60000;   // a cached installation token is dropped a minute before it ends
export const TOKEN_FALLBACK_MS = 300000; // an answer with no expiry is kept five minutes (Origin's tokens live <= 15)
export const CHECK_RUN_SETTINGS = ['ORIGIN_APP_PRIVATE_KEY', 'ORIGIN_APP_ID', 'ORIGIN_APP_INSTALLATION_ID'];
const SHA = /^[0-9a-f]{40}$/;

function json(body, status = 200) {
  return new Response(JSON.stringify(body, null, 1), { status, headers: { 'content-type': 'application/json' } });
}

function base64url(bytes) {
  let text = '';
  for (const byte of bytes) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function encoded(value) {
  return base64url(new TextEncoder().encode(JSON.stringify(value)));
}

function pemBytes(pem) {
  // A secret pasted with literal \n keeps working; the armour lines and whitespace are not the key.
  const body = String(pem).replace(/\\n/g, '\n').replace(/-----[^-]+-----/g, '').replace(/\s+/g, '');
  return Uint8Array.from(atob(body), (char) => char.charCodeAt(0));
}

const KEYS = new Map();
function signingKey(pem) {
  if (!KEYS.has(pem)) {
    KEYS.set(pem, crypto.subtle.importKey('pkcs8', pemBytes(pem), { name: 'Ed25519' }, false, ['sign'])
      .catch((error) => { KEYS.delete(pem); throw error; }));
  }
  return KEYS.get(pem);
}

export async function appJwt(pem, appId, nowS) {
  const input = `${encoded({ alg: 'EdDSA', typ: 'JWT' })}.${encoded({ iss: appId, aud: APP_AUDIENCE, iat: nowS, exp: nowS + APP_JWT_TTL_S })}`;
  const signature = await crypto.subtle.sign({ name: 'Ed25519' }, await signingKey(pem), new TextEncoder().encode(input));
  return `${input}.${base64url(new Uint8Array(signature))}`;
}

export const TOKENS = new Map();  // installation id -> { token, until }

class OriginRefused extends Error {}

export async function installationToken(env, now, fetcher, cache = TOKENS) {
  const id = String(env.ORIGIN_APP_INSTALLATION_ID);
  const held = cache.get(id);
  if (held && now < held.until) return held.token;
  let jwt;
  try {
    jwt = await appJwt(env.ORIGIN_APP_PRIVATE_KEY, env.ORIGIN_APP_ID, Math.floor(now / 1000));
  } catch {
    throw new OriginRefused('ORIGIN_APP_PRIVATE_KEY is not an Ed25519 PKCS#8 PEM key');
  }
  const base = env.ORIGIN_API_BASE || ORIGIN_API;
  const response = await fetcher(`${base}/app/installations/${encodeURIComponent(id)}/access_tokens`, {
    method: 'POST', headers: { authorization: `Bearer ${jwt}`, accept: 'application/json' } });
  if (!response.ok) throw new OriginRefused(`origin installation token answered ${response.status}`);
  const body = await response.json().catch(() => ({}));
  const token = body.token || body.accessToken || body.access_token;
  if (!token) throw new OriginRefused('origin installation token answered no token');
  const ends = Date.parse(body.expiresAt || body.expires_at || '');
  cache.set(id, { token, until: Number.isFinite(ends) ? ends - TOKEN_MARGIN_MS : now + TOKEN_FALLBACK_MS });
  return token;
}

// `same` is core.js's constant-time comparison, passed in so this module imports nothing.
export async function checkRunRoute(request, env, now, fetcher, same) {
  const missing = CHECK_RUN_SETTINGS.filter((name) => !env[name]);
  if (!env.EVENTS_TOKEN) missing.push('EVENTS_TOKEN');
  if (missing.length) return json({ error: `the check run is not configured (${missing.join(', ')})` }, 503);
  const header = request.headers.get('authorization') || '';
  if (!header.startsWith('Bearer ') || !same(header.slice('Bearer '.length), env.EVENTS_TOKEN)) {
    return json({ error: 'events token required' }, 401);
  }
  if (request.method !== 'POST') return json({ error: 'method not allowed' }, 405);
  const body = await request.json().catch(() => null);
  const repo = env.REPO || 'openuniversity-si/open-university';
  if (!body || body.repo !== repo) return json({ error: `only ${repo} is served` }, 400);
  if (!SHA.test(String(body.headSha)) || !body.checkRun || typeof body.checkRun !== 'object'
      || !body.checkSuite || typeof body.checkSuite !== 'object') {
    return json({ error: 'headSha (40 hex), checkSuite and checkRun required' }, 400);
  }
  const [owner, name] = repo.split('/');
  try {
    const token = await installationToken(env, now, fetcher);
    const base = env.ORIGIN_API_BASE || ORIGIN_API;
    const response = await fetcher(`${base}/repos/${encodeURIComponent(owner)}/${encodeURIComponent(name)}/check-runs`, {
      method: 'POST',
      headers: { authorization: `Bearer ${token}`, accept: 'application/json', 'content-type': 'application/json' },
      body: JSON.stringify({ headSha: body.headSha, checkSuite: body.checkSuite, checkRun: body.checkRun }),
    });
    if (response.status === 401) TOKENS.delete(String(env.ORIGIN_APP_INSTALLATION_ID));  // revoked: mint anew next time
    if (!response.ok) return json({ error: `origin check-runs answered ${response.status}` }, 502);
    const answer = await response.json().catch(() => ({}));
    return json({ outcome: answer.outcome ?? null });
  } catch (error) {
    if (error instanceof OriginRefused) return json({ error: error.message }, 502);
    return json({ error: 'origin unreachable' }, 502);
  }
}
