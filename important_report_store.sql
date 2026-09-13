begin;
insert into public.field_master(field_code,label_ja,entity_level,data_type,primary_source,diff_enabled,is_active) values
('building_name','建物名','building','text','important_report',true,true),
('display_address','住居表示','building','text','important_report',true,true),
('total_units','総戸数','building','number','important_report',true,true),
('completion_month','竣工年月','building','text','important_report',true,true),
('management_company','管理会社','building','text','important_report',true,true),
('management_type','管理形態','building','text','important_report',true,true),
('management_plan_status','管理計画認定','building','json','important_report',true,true),
('management_association','管理組合','building','json','important_report',true,true),
('governance_info','管理組合の運営','building','json','important_report',true,true),
('management_rules_effective_date','管理規約の施行・改定日','building','date','important_report',true,true),
('insurance_info','保険','building','json','important_report',true,true),
('common_exclusive_use_rules','共用部分の専用使用','building','json','important_report',true,true),
('parking_facility_info','駐車場','building','json','management_rules',true,true),
('bike_parking_info','駐輪場','building','json','important_report',true,true),
('trunk_room_info','トランクルーム','building','json','important_report',true,true),
('communications_info','通信設備','building','json','important_report',true,true),
('management_account_financials','管理費会計','building','json','important_report',true,true),
('repair_account_financials','修繕積立金会計','building','json','important_report',true,true),
('association_arrears','管理組合全体の滞納','building','json','important_report',true,true),
('association_loan_info','管理組合の借入','building','json','important_report',true,true),
('fee_change_plans','管理費等の変更予定','building','json','important_report',true,true),
('business_minpaku_restrictions','事務所・営業・民泊制限','building','json','management_rules',true,true),
('pet_restrictions','ペット制限','building','json','management_rules',true,true),
('instrument_restrictions','楽器制限','building','json','management_rules',true,true),
('renovation_restrictions','リフォーム制限','building','json','management_rules',true,true),
('long_term_repair_plan','長期修繕計画','building','json','important_report',true,true),
('repair_history','修繕履歴','building','json','important_report',true,true),
('major_repair_plan','大規模修繕予定','building','json','important_report',true,true),
('building_document_status','建築関係書類','building','json','important_report',true,true),
('unit_name','対象住戸の部屋番号','unit','text','important_report',true,true),
('management_fee','対象住戸の月額管理費（円）','unit','number','important_report',true,true),
('repair_reserve_fee','対象住戸の月額修繕積立金（円）','unit','number','important_report',true,true),
('unit_arrears','対象住戸の滞納','unit','json','important_report',true,true),
('other_monthly_fees','対象住戸のその他月額費用','unit','json','important_report',true,true),
('fee_payment_info','管理費等の支払方法','unit','json','important_report',true,true)
on conflict(field_code) do nothing;
update public.field_master set excel_named_range='重調_building_name' where field_code='building_name';
update public.field_master set excel_named_range='重調_unit_name' where field_code='unit_name';
alter table public.document_versions add column if not exists important_import_key text;
alter table public.document_versions add column if not exists important_raw_json jsonb;
alter table public.document_versions add column if not exists important_baseline jsonb;
alter table public.document_versions add column if not exists important_reviews jsonb not null default '[]';
create unique index if not exists important_import_key_unique on public.document_versions(important_import_key) where important_import_key is not null;

create or replace function public.save_important_report(p jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $fn$
declare
 uid uuid; bid uuid; did uuid; vid uuid; n integer; f record; oldv public.extracted_values;
 baseline jsonb:='{}'; diffs integer:=0; ident jsonb:=p->'identity'; src jsonb:=p->'source';
begin
 perform pg_catalog.pg_advisory_xact_lock(710904,2);
 if coalesce(src->>'file_hash','') !~ '^[a-f0-9]{64}$' or coalesce(p->>'import_key','') !~ '^[a-f0-9]{64}$'
    or p->'raw_json'->>'is_important_report' is distinct from 'true' then raise exception 'Invalid report'; end if;
 if p->>'source_type' not in ('seller_provided','company_obtained') or p->>'status' not in ('provisional','confirmed') then raise exception 'Invalid status'; end if;
 if nullif(ident->>'unit_id','') is not null then
   select u.unit_id,u.building_id into uid,bid from public.units u where u.unit_id=(ident->>'unit_id')::uuid;
   if uid is null then raise exception 'Unknown unit'; end if;
 elsif nullif(ident->>'house_number','') is not null then
   select count(*) into n from public.units where house_number=ident->>'house_number';
   if n=1 then select unit_id,building_id into uid,bid from public.units where house_number=ident->>'house_number'; end if;
 end if;
 if uid is null and coalesce(n,0)<=1 and nullif(ident->>'unit_id','') is null and nullif(ident->>'building_name','') is not null and nullif(ident->>'unit_name','') is not null and nullif(ident->>'display_address','') is not null then
   select count(*) into n from public.units u join public.buildings b using(building_id)
    where b.building_name=ident->>'building_name' and regexp_replace(u.unit_name,'[[:space:]]*号室$','')=ident->>'unit_name' and b.display_address=ident->>'display_address';
   if n=1 then select u.unit_id,u.building_id into uid,bid from public.units u join public.buildings b using(building_id)
    where b.building_name=ident->>'building_name' and regexp_replace(u.unit_name,'[[:space:]]*号室$','')=ident->>'unit_name' and b.display_address=ident->>'display_address'; end if;
 end if;
 select v.document_version_id,d.document_id into vid,did from public.document_versions v join public.documents d using(document_id)
  where v.important_import_key=p->>'import_key' or
   (d.document_type='important_report' and d.unit_id is not distinct from uid and v.file_hash=src->>'file_hash'
    and v.important_raw_json=p->'raw_json' and v.source_type=p->>'source_type' and v.status=p->>'status')
  order by v.uploaded_at limit 1;
 if vid is not null then return jsonb_build_object('document_version_id',vid,'document_id',did,'unit_id',uid,'needs_review',uid is null,'reused',true,'diffs_created',0); end if;
 if uid is not null then
   select document_id into did from public.documents where unit_id=uid and document_type='important_report' order by created_at limit 1;
 end if;
 if did is null then
   insert into public.documents(document_type,building_id,unit_id,title) values('important_report',bid,uid,'重要事項調査報告書') returning document_id into did;
 end if;
 select coalesce(max(version_no),0)+1 into n from public.document_versions where document_id=did;
 insert into public.document_versions(document_id,version_no,source_type,status,is_current,issuer_name,original_filename,file_hash,storage_path,important_import_key,important_raw_json)
 values(did,n,p->>'source_type',p->>'status',false,p->'raw_json'->>'issuer_name',src->>'original_filename',src->>'file_hash',src->>'storage_path',p->>'import_key',p->'raw_json') returning document_version_id into vid;
 for f in select key,value from jsonb_each(p->'raw_json'->'fields') loop
   if not exists(select 1 from public.field_master where field_code=f.key and is_active) then raise exception 'Unknown field'; end if;
   select e.* into oldv from public.extracted_values e join public.document_versions v using(document_version_id)
    where v.document_id=did and e.field_code=f.key and e.approved order by e.created_at desc limit 1;
   baseline:=baseline||jsonb_build_object(f.key,oldv.extracted_value_id);
   insert into public.extracted_values(document_version_id,field_code,value,confidence,source_label,source_section,source_text,page_no,value_as_of_date,reviewed,approved)
   values(vid,f.key,f.value->'value',(f.value->>'confidence')::numeric,f.value->>'source_label',f.value->>'source_section',f.value->>'source_text',
     (f.value->>'page_no')::integer,(f.value->>'value_as_of_date')::date,false,false);
   -- Unknown values are retained as unknown, never treated as zero/deletion.
   if oldv.extracted_value_id is not null and oldv.value is distinct from f.value->'value' then
    insert into public.value_diffs(document_id,old_version_id,new_version_id,field_code,old_value,new_value,review_status,affected_field)
     values(did,oldv.document_version_id,vid,f.key,oldv.value,f.value->'value','unreviewed',f.key);
    diffs:=diffs+1;
   end if;
 end loop;
 update public.document_versions set important_baseline=baseline where document_version_id=vid;
 return jsonb_build_object('document_version_id',vid,'document_id',did,'unit_id',uid,'needs_review',uid is null,'reused',false,'diffs_created',diffs);
end $fn$;

-- Only an explicit, authenticated administrative review may adopt a value.
-- The baseline prevents approving a stale review after another reviewer changed it.
create or replace function public.approve_important_report(p jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $fn$
declare
 v public.document_versions; d public.documents; e public.extracted_values; oldv public.extracted_values;
 code text; count_approved integer:=0;
begin
 perform pg_catalog.pg_advisory_xact_lock(710904,2);
 if nullif(btrim(p->>'reviewed_by'),'') is null then raise exception 'Reviewer required'; end if;
 select * into v from public.document_versions where document_version_id=(p->>'document_version_id')::uuid for update;
 select * into d from public.documents where document_id=v.document_id;
 if d.document_type is distinct from 'important_report' or d.unit_id is null then raise exception 'Unit confirmation required'; end if;
 for code in select jsonb_array_elements_text(p->'field_codes') loop
   select * into e from public.extracted_values where document_version_id=v.document_version_id and field_code=code;
   if e.extracted_value_id is null or e.value is null or e.value='null'::jsonb or nullif(e.source_text,'') is null or e.page_no is null then raise exception 'Evidence required'; end if;
   if coalesce((v.important_raw_json->'fields'->code->>'needs_review')::boolean,true)
      and coalesce((p->>'verified_against_original')::boolean,false) is not true then raise exception 'Resolve reading uncertainty before approval'; end if;
   if e.approved then continue; end if;
   select x.* into oldv from public.extracted_values x join public.document_versions dv using(document_version_id)
     where dv.document_id=d.document_id and x.field_code=code and x.approved order by x.created_at desc limit 1;
   if oldv.extracted_value_id::text is distinct from v.important_baseline->>code then raise exception 'Review is stale'; end if;
   if oldv.value_as_of_date is not null and (e.value_as_of_date is null or e.value_as_of_date<oldv.value_as_of_date) then raise exception 'Older or unknown reference date'; end if;
   update public.extracted_values set approved=false where extracted_value_id=oldv.extracted_value_id;
   update public.extracted_values set reviewed=true,approved=true where extracted_value_id=e.extracted_value_id;
   update public.value_diffs set review_status='applied',reviewed_at=now(),reviewed_by=p->>'reviewed_by'
     where new_version_id=v.document_version_id and field_code=code and review_status='unreviewed';
   count_approved:=count_approved+1;
 end loop;
 update public.document_versions dv set is_current=exists(select 1 from public.extracted_values ev where ev.document_version_id=dv.document_version_id and ev.approved)
   where dv.document_id=d.document_id;
 update public.document_versions set important_reviews=important_reviews||jsonb_build_array(jsonb_build_object(
   'reviewed_by',p->>'reviewed_by','reviewed_at',now(),'field_codes',p->'field_codes',
   'verified_against_original',coalesce((p->>'verified_against_original')::boolean,false))) where document_version_id=v.document_version_id;
 return jsonb_build_object('document_version_id',v.document_version_id,'approved_count',count_approved);
end $fn$;

create or replace function public.get_approved_important_report(p jsonb)
returns jsonb language sql security invoker set search_path='' as $fn$
 select jsonb_build_object('document_version_id',p->>'document_version_id','fields',coalesce(jsonb_object_agg(e.field_code,jsonb_build_object(
 'value',e.value,'approved',true,'confidence',e.confidence,'needs_review',coalesce((v.important_raw_json->'fields'->e.field_code->>'needs_review')::boolean,true),'source_text',e.source_text,'page_no',e.page_no,'value_as_of_date',e.value_as_of_date,'document_version_id',e.document_version_id)) filter(where e.field_code is not null),'{}'))
 from public.document_versions v join public.documents d using(document_id)
 join public.extracted_values e using(document_version_id)
 where v.document_version_id=(p->>'document_version_id')::uuid and d.document_type='important_report' and d.unit_id is not null and e.approved;
$fn$;
revoke all on function public.save_important_report(jsonb), public.approve_important_report(jsonb), public.get_approved_important_report(jsonb) from public,anon,authenticated;
grant execute on function public.save_important_report(jsonb), public.approve_important_report(jsonb), public.get_approved_important_report(jsonb) to service_role;
commit;
