// Shared server-side helpers for Netlify functions. Secrets come only from environment variables.
export const AUTH_URL = 'https://afdtohxuzuwlqmjbrpar.supabase.co';
export const AUTH_KEY = 'sb_publishable_4I1EXj6iMy3J-_nxBrOasw_1CRPXyw4';
export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;

export class Failure extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export function reply(status, body) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' } });
}

export function config() {
  const url = (process.env.SUPABASE_URL || '').replace(/\/$/, '');
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY || '';
  if (!/^https:\/\/[a-z0-9]+\.supabase\.co$/.test(url) || !key) throw new Failure(500, '初期設定が完了していません。管理者へ連絡してください。');
  return { url, key };
}

export async function authenticate(request) {
  const authorization = request.headers.get('authorization') || '';
  if (!authorization.startsWith('Bearer ')) throw new Failure(401, 'ログインし直してください。');
  const response = await fetch(`${AUTH_URL}/auth/v1/user`, { headers: { apikey: AUTH_KEY, authorization } });
  if (!response.ok) throw new Failure(401, 'ログインし直してください。');
  const user = await response.json();
  if (!allowedEmail(user.email, process.env.ALLOWED_EMAILS)) throw new Failure(403, 'このアカウントは利用できません。管理者に利用登録を依頼してください。');
  return user;
}

// ALLOWED_EMAILS is a comma-separated list of addresses and "@domain" entries
// (e.g. "@tokyoms.co.jp,someone@gmail.com"). An empty list lets nobody in: anyone can
// sign in with Google, so an unset list must not mean "everyone".
export function allowedEmail(email, list) {
  const address = String(email || '').trim().toLowerCase();
  const entries = String(list || '').split(',').map(v => v.trim().toLowerCase()).filter(Boolean);
  if (!address.includes('@')) return false;
  const domain = address.slice(address.lastIndexOf('@'));
  return entries.some(entry => entry.startsWith('@') ? entry === domain : entry === address);
}

const RPC_MESSAGES = {
  'Evidence review required': '根拠（確信度・ページ・原文）が不十分なため、この内容は採用できません。原本を確認してください。',
  'Master changed; reload': '確定値が別の操作で変わりました。画面を再読み込みしてから選び直してください。',
  'Unit mismatch': '案件と資料の住戸が一致しません。',
  'Not reviewable': 'この項目はすでに処理済みです。',
  'Invalid decision': '選択内容を確認してください。',
  'Unsupported field': 'この項目は現在採用に対応していません。',
  'Missing target': '対象の建物・住戸が見つかりません。',
  'Missing master': '確定値の対象欄が見つかりません。',
  'Unsupported registry diff': 'この項目は現在、謄本からの採用に対応していません。',
  'Unsupported document': 'この資料の種類では採用できません。',
  'Case mismatch': '案件と資料が一致しません。',
  'Stale review': '確認内容が古くなっています。画面を再読み込みしてください。',
  'Source mismatch': '資料と案件が一致しません。',
};

export async function db(path, options = {}) {
  const { url, key } = config();
  const response = await fetch(`${url}/rest/v1/${path}`, { ...options, headers: { apikey: key, authorization: `Bearer ${key}`, 'Content-Type': 'application/json', ...(options.headers || {}) } });
  if (!response.ok) {
    // Surface a plpgsql `raise exception` message (PostgREST returns it as {message, code}) so
    // review confirmations can tell the user *why* a candidate was rejected, not just that it was.
    if (path.startsWith('rpc/')) {
      let body = null;
      try { body = await response.json(); } catch { /* not JSON */ }
      if (body?.message) throw new Failure(409, RPC_MESSAGES[body.message] || body.message);
    }
    throw new Failure(502, 'データベースに接続できませんでした。');
  }
  return response.status === 204 ? null : response.json();
}
