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
            try:self.end_headers();self.wfile.write(body)
            except (ConnectionError,OSError):pass
        def do_GET(self):
            if not self.allowed():return self.send(403,{'error':'接続先が不正です。'})
            path=urlsplit(self.path).path
            if path in ('/api/mapping','/api/mapping.csv'):
                from web_mapping import inventory,export_csv
                try:rows=inventory(workspace.template)
                except (OSError,ValueError):return self.send(409,{'error':'ひな形・マッピング設定を確認してください。'})
                if path.endswith('.csv'):return self.send(200,export_csv(rows),'text/csv; charset=utf-8','excel_mapping_status.csv')
                return self.send(200,{'rows':rows})
            if path=='/api/state':
                with workspace.lock:return self.send(200,{**workspace.public(),'csrf':token})
            if path.startswith('/download/'):
                item=workspace.files.get(path.removeprefix('/download/'))
                if not item or not item.is_file():return self.send(404,{'error':'ファイルがありません。再生成してください。'})
                return self.send(200,item.read_bytes(),'application/vnd.ms-excel.sheet.macroEnabled.12',item.name)
            files={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
            for sheet in ('theme','base','layout','components'):
                files['/styles/'+sheet+'.css']=('styles/'+sheet+'.css','text/css; charset=utf-8')
            if path not in files:return self.send(404,{'error':'ページがありません。'})
            name,kind=files[path];return self.send(200,(ROOT/'web'/name).read_bytes(),kind)
        def do_POST(self):
            allowed_origins=(f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}')
            if not self.allowed() or self.headers.get('Origin') not in allowed_origins or not secrets.compare_digest(self.headers.get('X-CSRF-Token',''),token):
                return self.send(403,{'error':'画面を再読込してください。'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if urlsplit(self.path).path in ('/api/upload-registry','/api/upload-report','/api/upload-documents','/api/prepare-documents'):
                    if not 0<size<=40*1024*1024:raise StoreError('PDF合計サイズは40MB以内にしてください。')
                    from email.parser import BytesParser
                    from email.policy import default
                    from web_registry import upload
                    content_type=self.headers.get('Content-Type','')
                    if not content_type.startswith('multipart/form-data'):raise ValueError()
                    message=BytesParser(policy=default).parsebytes(('Content-Type: '+content_type+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+self.rfile.read(size))
                    files=[(p.get_filename(),p.get_payload(decode=True)) for p in message.iter_parts() if p.get_filename()]
                    with workspace.lock:
                        if urlsplit(self.path).path in ('/api/upload-documents','/api/prepare-documents'):
                            from web_documents import upload as upload_documents
                            form={part.get_param('name',header='content-disposition'):part.get_content() for part in message.iter_parts() if not part.get_filename()}
                            kinds=json.loads(form.get('kinds','[]'))
                            if len(kinds)!=len(files):raise ValueError()
                            from web_ai_cost import prepare,authorize,summary
                            uploads=[(k,n,v) for k,(n,v) in zip(kinds,files)]
                            if urlsplit(self.path).path=='/api/prepare-documents':return self.send(200,prepare(workspace,uploads,form.get('case_id')))
                            plan=authorize(workspace,form.get('plan_token'),uploads,form.get('ai_confirmed')=='true')
                            before=workspace.ai_calls
                            result=upload_documents(workspace,form.get('case_id'),uploads)
                            from web_registration import advance
                            result=advance(workspace,result)
                            result=summary(workspace,plan,uploads,result,before)
                        elif urlsplit(self.path).path=='/api/upload-report':
                            from web_report import upload as upload_report
                            cid=next((part.get_content() for part in message.iter_parts() if part.get_param('name',header='content-disposition')=='case_id' and not part.get_filename()),None)
                            if not isinstance(cid,str) or len(cid)>200:raise ValueError()
                            result=upload_report(workspace,cid,files)
                        else:result=upload(workspace,files)
                    return self.send(200,result)
                if not 0<size<(65536 if urlsplit(self.path).path=='/api/verify-purchase' else 8192):raise ValueError()
                p=json.loads(self.rfile.read(size));path=urlsplit(self.path).path
                if path=='/api/choice':
                    from web_choices import choose
                    with workspace.lock:result=choose(workspace,p['case_id'],p['kind'],p['key'],p['source'])
                elif path=='/api/decision':result=workspace.decide(p['case_id'],p['diff_id'],p['action'])
                elif path=='/api/generate':result=workspace.generate(p['case_id'])
                elif path=='/api/verify-purchase':
                    from web_purchase import verify_fields
                    with workspace.lock:result=verify_fields(workspace,p['case_id'],p['fields'],p['property_type'])
                elif path=='/api/select-candidate':
                    from web_registration import choose_candidate
                    with workspace.lock:result=choose_candidate(workspace,p['token'],p['candidate_id'])
                elif path=='/api/auto-register':
                    from web_registration import advance
                    with workspace.lock:result=advance(workspace,{'state':workspace.public(),'case_id':p['case_id']})
                elif path=='/api/registration-preview':
                    from web_registration import preview
                    with workspace.lock:result=preview(workspace,p['case_id'])
                elif path=='/api/register-case':
                    from web_registration import register
                    with workspace.lock:result=register(workspace,p['token'],p['case_mode'],p.get('resume_case_id'))
                elif path=='/api/retry-documents':
                    from web_documents import flush
                    with workspace.lock:
                        workspace.case(p['case_id']);warning=flush(workspace,p['case_id'],p['case_id'])
                        result={'state':workspace.public(),'case_id':p['case_id'],'warning':warning}
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
        from web_data import load_env
        load_env()
        if '--no-browser' not in sys.argv:
            import urllib.request
            try:
                url='http://127.0.0.1:'+str(int(env('WEB_PORT') or '8765'))
                with urllib.request.urlopen(url+'/api/state',timeout=2) as r:running=json.load(r)
                if 'cases' in running and 'csrf' in running:
                    webbrowser.open(url);sys.exit(0)
            except (OSError,ValueError):pass
        workspace=Workspace();server=make_server(workspace,int(env('WEB_PORT') or '8765'))
        url=f'http://127.0.0.1:{server.server_port}'
        print('契約書作成画面: '+url,flush=True)
        if '--no-browser' not in sys.argv:webbrowser.open(url)
        server.serve_forever()
    except (StoreError,OSError,ValueError) as e:
        print('起動できませんでした。環境変数、ひな形、起動済み画面を確認してください。',flush=True)
        sys.exit(1)
