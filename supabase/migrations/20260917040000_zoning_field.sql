-- Zoning/city-planning reference data. No RPC or new table: it reuses documents
-- (document_type='zoning', a plain text column, needs no enum change) and
-- extracted_values (field_code='zoning_info', value holds the zones array).
-- Unversioned/undiffed for now (diff_enabled=false) — a later pass can add proper
-- per-zone review the way registry/report/rules already have.
insert into public.field_master(field_code,label_ja,entity_level,data_type,primary_source,diff_enabled,is_active,notes) values
 ('zoning_info','用途地域・都市計画情報','building','json','用途地域資料',false,true,'区域ごとの配列。バージョン管理・差分未対応')
on conflict (field_code) do nothing;
