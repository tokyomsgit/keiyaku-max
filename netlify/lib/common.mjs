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
  const allowed = (process.env.ALLOWED_EMAILS || '').split(',').map(v => v.trim().toLowerCase()).filter(Boolean);
  if (allowed.length && !allowed.includes(String(user.email || '').toLowerCase())) throw new Failure(403, 'このアカウントは利用できません。');
  return user;
}

export async function db(path, options = {}) {
  const { url, key } = config();
  const response = await fetch(`${url}/rest/v1/${path}`, { ...options, headers: { apikey: key, authorization: `Bearer ${key}`, 'Content-Type': 'application/json', ...(options.headers || {}) } });
  if (!response.ok) throw new Failure(502, 'データベースに接続できませんでした。');
  return response.status === 204 ? null : response.json();
}
