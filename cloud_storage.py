"""Private Supabase Storage access for the cloud worker. Service key stays server-side."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from web_data import env, StoreError

BUCKET = 'keiyaku-private'


class Storage:
    def __init__(self, bucket=BUCKET):
        self.url = (env('SUPABASE_URL') or '').rstrip('/')
        self.key = env('SUPABASE_SERVICE_ROLE_KEY') or ''
        if not re.fullmatch(r'https://[a-z0-9]+\.supabase\.co', self.url) or not self.key:
            raise StoreError('Supabaseの接続設定を確認してください。')
        self.bucket = bucket

    def _request(self, method, path, body=None, headers=None, missing_ok=False):
        request = urllib.request.Request(self.url + '/storage/v1/' + path, data=body, method=method,
            headers={'apikey': self.key, 'Authorization': 'Bearer ' + self.key, **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            if missing_ok and exc.code in (400, 404):
                return None
            raise StoreError('非公開ストレージの操作に失敗しました。') from None
        except OSError:
            raise StoreError('非公開ストレージに接続できませんでした。') from None

    def _object(self, name):
        if not re.fullmatch(r'[a-z]+/[A-Za-z0-9._-]+', name):
            raise StoreError('保存先が不正です。')
        return 'object/' + self.bucket + '/' + urllib.parse.quote(name)

    def get(self, name):
        return self._request('GET', self._object(name), missing_ok=True)

    def put(self, name, content, kind='application/octet-stream'):
        self._request('POST', self._object(name), content, {'Content-Type': kind, 'x-upsert': 'true'})

    def get_json(self, name):
        data = self.get(name)
        return None if data is None else json.loads(data.decode('utf8'))

    def put_json(self, name, value):
        self.put(name, json.dumps(value, ensure_ascii=False).encode('utf8'), 'application/json')

    def ensure_bucket(self):
        body = json.dumps({'id': self.bucket, 'name': self.bucket, 'public': False,
            'file_size_limit': 50 * 1024 * 1024}).encode()
        if self._request('GET', 'bucket/' + self.bucket, missing_ok=True) is None:
            self._request('POST', 'bucket', body, {'Content-Type': 'application/json'})
        info = json.loads(self._request('GET', 'bucket/' + self.bucket))
        if info.get('public'):
            raise StoreError('保存先バケットが公開設定です。停止しました。')
        return info
