-- Management rules OCR support adds three field codes the reader now extracts
-- (management_rules_mapping.json) that had no field_master row yet. The other
-- newly-wired codes (common_exclusive_use_rules, bike_parking_info,
-- management_type) already exist from earlier report-focused migrations.
insert into public.field_master(field_code,label_ja,entity_level,data_type,primary_source,diff_enabled,is_active,notes) values
 ('management_staff_hours','管理員勤務','building','text','管理規約',true,true,'OCR対応'),
 ('prohibited_matters','禁止事項','building','text','管理規約',true,true,'OCR対応'),
 ('approval_required_matters','届出・承認が必要な事項','building','text','管理規約',true,true,'OCR対応')
on conflict (field_code) do nothing;
