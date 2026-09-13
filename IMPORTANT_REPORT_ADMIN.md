# 重調の追加機能

`important_report_store.sql` をSupabaseへ適用。既存の謄本RPC・日本語JSON・Excel転記には変更なし。
サービスキーは既存の `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` 環境変数だけで管理する。
読取は `OPENAI_API_KEY` と既存の `OPENAI_MODEL`（未指定時 gpt-4.1）を使用。
Python依存: pypdf、pypdfium2、Pillow、openpyxl。特殊な日本語フォントのPDFにはPATH上の `pdftoppm` が必要。

スクリプト所在: `plugins/tohon-keiyakusho/skills/tohon-nyuryoku/scripts/`

```text
python important_report_store.py import 報告書.pdf --unit-id 既存住戸UUID
python important_report_store.py approve 資料版UUID --fields management_fee repair_reserve_fee --reviewed-by 確認者
python important_report_store.py export 資料版UUID 名前定義付き契約書.xlsm -o 出力.xlsm
```

自社取得版はimportに `--source-type company_obtained --status confirmed` を指定する。
confirmedは資料の取得状態であり、自動承認ではない。原本確認済みの指定項目だけapproveする。
画像や根拠不一致の項目は、原本との照合後だけ `--verified-against-original` を指定する。
誤読を修正する場合は標準JSONのvalueと根拠を修正し、Pythonの `save_to_supabase(data, unit_id=...)` で別版として保存する。旧版は保持される。
曖昧な物件の新規作成はしない。未照合資料はunit_idなしで保存し、承認・出力を禁止する。
住戸確認後は同じキャッシュを使い、正しいunit_idを付けて再投入する。

採用値は `extracted_values.approved` と版ごとの `important_reviews` に保持する。
既存buildings/unitsの確定値は変更しない。差分は前回採用値と比較し、未承認値はExcelへ渡さない。
基準日不明や古い値による既採用値の置換は停止する。資料全体の発行日で補完しない。
管理規約との出典優先はmappingのprimary_sourceとdocument_typeで区別可能。

正式ひな形の既存31名前定義を保持し、基本入力の物件名と号室へ以下を追加する。

- `building_name` → `重調_building_name`
- `unit_name` → `重調_unit_name`（末尾の「号室」だけ除去、先頭ゼロは保持）

名前の付与は `python add_important_report_names.py 元ひな形.xlsm 別名ひな形.xlsm`。
付与専用の `important_report_template_names.json` が入力欄ラベル・参照先を管理する。
アプリの転記は `important_report_mapping.json` の名前定義だけを利用し、固定セルを参照しない。
管理費・修繕積立金等は基本入力に適切な欄がないため、残り33項目はExcel未対応・Supabase保存のみ。
承認済みでも、needs_reviewがfalseでない値、confidenceが0.85未満または不明な値、根拠不明な値は自動転記しない。
出力では数式・VBA・書式等を維持し、Excelで開いたときの再計算だけ要求する。
正式ひな形自体は名前追加以外変更しない。対応項目0件の場合は契約書コピーを生成しない。
原本はstorage_pathで追跡し、Storageへのアップロードは未実装。OCR画像はメモリ内のみ。
キャッシュ・原本・出力はGit管理対象外の場所に保存する。

検証: `python -m unittest test_important_report test_supabase_store test_important_report_names`。
`test_important_report_db.sql` は実DBに対して実行でき、試験データをROLLBACKする。
