"""Loopback-only UI. No AI routes, arbitrary paths, or browser-side service keys."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
import webbrowser
from urllib.parse import urlsplit
from web_data import Workspace,StoreError,ROOT,env


def make_server(workspace,port=8765):
    token=secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def allowed(self):return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')
        def send(self,status,body,kind='application/json; charset=utf-8',filename=None):
            if not isinstance(body,bytes):body=json.dumps(body,ensure_ascii=False).encode('utf8')
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Referrer-Policy','no-referrer');self.send_header('X-Frame-Options','DENY')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            if filename:
                from urllib.parse import quote
                self.send_header('Content-Disposition',"attachment; filename*=UTF-8''"+quote(filename))
            self.end_headers();self.wfile.write(body)
        def do_GET(self):
            if not self.allowed():return self.send(403,{'error':'接続先が不正です。'})
            path=urlsplit(self.path).path
            if path=='/api/state':
                with workspace.lock:return self.send(200,{**workspace.public(),'csrf':token})
            if path.startswith('/download/'):
                item=workspace.files.get(path.removeprefix('/download/'))
                if not item or not item.is_file():return self.send(404,{'error':'ファイルがありません。再生成してください。'})
                return self.send(200,item.read_bytes(),'application/vnd.ms-excel.sheet.macroEnabled.12',item.name)
            files={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
            if path not in files:return self.send(404,{'error':'ページがありません。'})
            name,kind=files[path];return self.send(200,(ROOT/'web'/name).read_bytes(),kind)
        def do_POST(self):
            allowed_origins=(f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}')
            if not self.allowed() or self.headers.get('Origin') not in allowed_origins or not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),token):
                return self.send(403,{'error':'画面を再読込してください。'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<8192:raise ValueError()
                p=json.loads(self.rfile.read(size));path=urlsplit(self.path).path
                if path=='/api/decision':result=workspace.decide(p['case_id'],p['diff_id'],p['action'])
                elif path=='/api/generate':result=workspace.generate(p['case_id'])
                elif path=='/api/refresh':
                    with workspace.lock:workspace.refresh();result=workspace.public()
                else:return self.send(404,{'error':'操作がありません。'})
                self.send(200,result)
            except StoreError as e:self.send(409,{'error':str(e)})
            except (ValueError,KeyError,TypeError):self.send(400,{'error':'入力内容を確認してください。'})
            except Exception:self.send(500,{'error':'処理を完了できませんでした。管理者へ連絡してください。'})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler);server.daemon_threads=True
    return server


if __name__=='__main__':
    try:
        workspace=Workspace();server=make_server(workspace,int(env('WEB_PORT') or '8765'))
        url=f'http://127.0.0.1:{server.server_port}'
        print('契約書作成画面: '+url,flush=True)
        if '--no-browser' not in sys.argv:webbrowser.open(url)
        server.serve_forever()
    except (StoreError,OSError,ValueError) as e:
        print('起動できませんでした。環境変数、ひな形、起動済み画面を確認してください。',flush=True)
        sys.exit(1)
