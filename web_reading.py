"""Safe errors around existing readers; no extraction logic lives here."""
from web_data import StoreError

def read_existing(reader, pdf, *args, **kwargs):
    from pypdf import PdfReader
    try:
        document=PdfReader(str(pdf))
        if document.is_encrypted and not document.decrypt(''):
            raise StoreError('対応していないPDF：パスワードを解除して再選択してください。')
        if not len(document.pages):raise StoreError('対応していないPDF：ページがありません。')
    except StoreError:raise
    except Exception:raise StoreError('対応していないPDF：ファイルが破損している可能性があります。') from None
    try:
        return reader(pdf,*args,**kwargs)
    except Exception as exc:
        chain=[];current=exc
        for _ in range(4):
            if current is None:break
            chain.append(str(current).lower());current=current.__context__
        message=' '.join(chain)
        if '401' in message or 'api_key' in message or '初期設定' in message:
            reason='API設定不足：管理者がAPIキーを確認してください。'
        elif '429' in message or 'quota' in message:
            reason='API利用上限：時間をおくか、管理者へ連絡してください。'
        elif 'timeout' in message or 'timed out' in message:
            reason='API接続タイムアウト：時間をおいて再実行してください。'
        elif any(x in message for x in ('connection','getaddrinfo','urlopen','接続')):
            reason='API接続エラー：ネットワーク・API設定を管理者が確認してください。'
        elif isinstance(exc,StoreError):raise
        else:reason='読取処理エラー：PDFの内容とAPI接続を管理者が確認してください。'
        raise StoreError(reason) from None
