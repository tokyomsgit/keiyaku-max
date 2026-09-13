# Supabase保存の管理者設定

`supabase_store.sql` を対象DBへ適用し、環境変数 `SUPABASE_URL` と `SUPABASE_SERVICE_ROLE_KEY` を設定してください。キーはサーバーまたは管理者が管理する実行環境でのみ使用してください。`.env` は自動読込しません。

Claude版の実行入口は `scripts/store_and_fill.py` です。中間JSONの形式、`reading-rules.md`、`fill_tohon.py`、`mapping.json` は変更していません。

```text
python store_and_fill.py 中間JSON ひな形.xlsm -o 出力.xlsm --source 原本PDF --house-number 完全な家屋番号
```

既存の日本語JSONには家屋番号の末尾しかないため、全文は原文で確認して引数へ渡します。建物名・抵当権・根拠は構造化されていないため、欠落を「なし」と解釈しません。確認済みの補足がある場合のみ、別ファイルを `--db-context` で渡せます。対応キーは `building_name`、`active_mortgages`、`source_type`、`status`、`as_of_date`、`evidence` です。元JSONは変更しません。

`evidence` は日本語の項目パスをキーとして、存在する `confidence`、`source_text`、`page_no`、`value_as_of_date` のみ指定します。

資料の初期値は seller_provided / provisional。資料属性が変わった再保存は新しい版として保持します。既存マスターは上書きせず、変更は value_diffs の未確認差分になります。Excelは保存した入力JSONから生成するため、マスターと未承認差分は区別してください。

DB保存は単一トランザクションです。同じ入力・資料属性・補足の再試行は同じ版を返します。通信失敗時はExcelを生成せず、同じ入力で再実行できます。

`fill_tohon.py` の終了コード1は既存仕様では要確認を含みます。Excel生成の有無と既存の警告を確認してください。

検証：`python -m unittest test_supabase_store`
