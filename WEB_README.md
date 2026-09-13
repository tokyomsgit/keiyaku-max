1. **環境変数設定**：`.env.example`を`.env`へコピー。`DEMO_MODE=true`、`DEMO_WRITE_DB=false`でDB接続もAI呼出しも行いません。`DEMO_REGISTRY_JSON`に既存のClaude形式の中間JSON、`DEMO_EVIDENCE_JSON`に根拠付きintegrated.json、`DEMO_REPORT_JSON`に解析済み重調JSON、`CONTRACT_TEMPLATE`に名前定義付きxlsmを指定。本番は`DEMO_MODE=false`と既存のSupabase環境変数を使用し、管理者が`web_workspace.sql`を一度適用します。`DEMO_WRITE_DB=true`は実DBの読書きを有効にするため、通常の画面確認ではfalseのままにしてください。
2. **起動方法**：`run_local.bat`をダブルクリック。既存のPython環境（openpyxl）を使います。コマンドでは`python web_app.py`。終了は起動したウィンドウでCtrl+C。デモの採用・保留は起動中のメモリだけに保存され、再起動で戻ります。`DEMO_APPROVED_FIELDS`には、原本確認済みの重調項目だけをカンマ区切りで指定します。
3. **ブラウザURL**：`http://127.0.0.1:8765`。このPCだけで操作できます。外部へ実データやひな形を公開しません。

公開デモは python build_public_demo.py で生成します。公開対象は public-demo-dist の5ファイルだけです。ダミーデータで動作し、AI・DB接続・Excel生成は行いません。差分の操作は再読込で戻ります。ローカル版は従来どおり起動できます。

ローカルの「謄本PDFを追加」は同一住戸の建物・土地PDFを最大12件、合計40MBまで受け付けます。SHA256が一致する解析済みJSONを優先します。DEMO_MODE=trueでは未解析PDFを解析しません。新規解析はDEMO_MODE=falseと既存のOPENAI_API_KEY設定が必要です。既存読取プログラムは親フォルダから読み込みます（必要時のみREGISTRY_READER_ROOTで変更）。

画面からのPDF取込結果はローカルに保存・再起動時に復元します。新規取込のDB自動登録と重調の自動紐付けは行いません。既存DB案件の確認・差分採用は従来どおりです。戸建て・判定不能・資料間の対応未確定はExcel生成を停止します。起動済みの場合はrun_local.batで画面だけを開きます。
