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

現行正式ひな形の独自名前定義31件は謄本・住居表示用。重調35項目との確実な対応はないため、
`important_report_mapping.json` のexcel_named_rangeはnull。無理な固定セル転記は行わず、要確認として返す。
管理者がひな形の対応する名前定義を整備して対応表に登録した項目だけ反映できる。
対応項目0件の場合は空の契約書コピーを生成しない。元ひな形は変更しない。
原本はstorage_pathで追跡し、Storageへのアップロードは未実装。OCR画像はメモリ内のみ。
キャッシュ・原本・出力はGit管理対象外の場所に保存する。

検証: `python -m unittest test_important_report test_supabase_store`。
`test_important_report_db.sql` は実DBに対して実行でき、試験データをROLLBACKする。
