alter table public.document_versions add column if not exists management_rules_raw_json jsonb;
insert into public.field_master(field_code,label_ja,entity_level,data_type,primary_source,diff_enabled,is_active) values
('unit_use_restrictions','専有部分の用途制限','building','text','management_rules',true,true),('office_use_allowed','事務所利用','building','text','management_rules',true,true),('pet_restrictions','ペット制限','building','text','management_rules',true,true),('instrument_restrictions','楽器制限','building','text','management_rules',true,true),('balcony_exclusive_use','バルコニー専用使用','building','text','management_rules',true,true),('private_garden_rules','専用庭','building','text','management_rules',true,true),('door_window_exclusive_use','玄関扉・窓の専用使用','building','text','management_rules',true,true),('parking_rules','駐車場規則','building','text','management_rules',true,true),('renovation_restrictions','リフォーム制限','building','text','management_rules',true,true),('leasing_restrictions','賃貸制限','building','text','management_rules',true,true),('management_association_name','管理組合名','building','text','management_rules',true,true),('voting_rights_rule','議決権','building','text','management_rules',true,true),('rules_effective_date','規約施行日','building','text','management_rules',true,true),('related_rules','関連する使用細則','building','text','management_rules',true,true) on conflict(field_code) do nothing;

create or replace function public.save_management_rules(p jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare bid uuid;did uuid;vid uuid;oldv public.extracted_values;n int;f record;diffs int:=0;
begin
 perform pg_catalog.pg_advisory_xact_lock(710904,3);
 select u.building_id into bid from public.cases c join public.units u using(unit_id) where c.case_id=(p->>'case_id')::uuid;
 if bid is null or bid is distinct from (p->>'building_id')::uuid then raise exception 'Building/case mismatch';end if;
 if coalesce(p->'source'->>'file_hash','') !~ '^[a-f0-9]{64}$' or p->'raw_json'->>'is_management_rules' is distinct from 'true' then raise exception 'Invalid rules';end if;
 select v.document_version_id,v.document_id into vid,did from public.document_versions v join public.documents d using(document_id)
 where d.building_id=bid and d.unit_id is null and d.document_type='management_rules' and v.file_hash=p->'source'->>'file_hash';
 if vid is not null then return jsonb_build_object('document_version_id',vid,'document_id',did,'building_id',bid,'reused',true,'diffs_created',0);end if;
 select document_id into did from public.documents where document_type='management_rules' and building_id=bid and unit_id is null order by created_at limit 1;
 if did is null then insert into public.documents(document_type,building_id,title) values('management_rules',bid,'管理規約') returning document_id into did;end if;
 select coalesce(max(version_no),0)+1 into n from public.document_versions where document_id=did;
 insert into public.document_versions(document_id,version_no,source_type,status,original_filename,file_hash,storage_path,management_rules_raw_json)
 values(did,n,'seller_provided','provisional',p->'source'->>'original_filename',p->'source'->>'file_hash',p->'source'->>'storage_path',p->'raw_json') returning document_version_id into vid;
 for f in select * from jsonb_each(p->'raw_json'->'fields') loop
  if not exists(select 1 from public.field_master where field_code=f.key and is_active) then raise exception 'Unknown field';end if;
  select e.* into oldv from public.extracted_values e join public.document_versions v using(document_version_id)
   where v.document_id=did and e.field_code=f.key order by e.approved desc,v.version_no desc limit 1;
  insert into public.extracted_values(document_version_id,field_code,value,confidence,source_article,source_section,source_text,page_no)
   values(vid,f.key,f.value->'value',(f.value->>'confidence')::numeric,f.value->>'source_article',f.value->>'source_section',f.value->>'source_text',(f.value->>'page_no')::int);
  if oldv.extracted_value_id is not null and oldv.value is distinct from f.value->'value' then
   insert into public.value_diffs(document_id,old_version_id,new_version_id,field_code,old_value,new_value,review_status,affected_field)
    values(did,oldv.document_version_id,vid,f.key,oldv.value,f.value->'value','unreviewed','management_rules.'||f.key);diffs:=diffs+1;
  end if;
 end loop;
 return jsonb_build_object('document_version_id',vid,'document_id',did,'building_id',bid,'reused',false,'diffs_created',diffs);
end $$;
create or replace function public.review_management_rules_diff(p jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare bid uuid;f public.value_diffs;e public.extracted_values;v public.document_versions;oldvalue jsonb;
begin
 perform pg_catalog.pg_advisory_xact_lock(710904,3);
 select u.building_id into bid from public.cases c join public.units u using(unit_id) where c.case_id=(p->>'case_id')::uuid;
 select q.* into f from public.value_diffs q join public.documents d using(document_id) where q.diff_id=(p->>'diff_id')::uuid and d.document_type='management_rules' and d.building_id=bid;
 if f.diff_id is null then raise exception 'Case mismatch';end if;
 if f.review_status='applied' then return jsonb_build_object('reused',true);end if;
 if p->>'action'='hold' then update public.value_diffs set review_status='reviewed',reviewed_at=now(),reviewed_by='local-web' where diff_id=f.diff_id;return jsonb_build_object('review_status','reviewed');end if;
 select * into e from public.extracted_values where document_version_id=f.new_version_id and field_code=f.field_code;
 select * into v from public.document_versions where document_version_id=f.new_version_id;
 if p->>'action' is distinct from 'adopt' or e.value='null' or e.value is null or e.value is distinct from f.new_value or e.confidence is null or e.confidence<.85
  or nullif(e.source_text,'') is null or e.page_no is null or coalesce((v.management_rules_raw_json->'fields'->f.field_code->>'needs_review')::boolean,true) then raise exception 'Evidence review required';end if;
 select x.value into oldvalue from public.extracted_values x join public.document_versions dv using(document_version_id)
  where dv.document_id=f.document_id and dv.document_version_id<>f.new_version_id and x.field_code=f.field_code order by x.approved desc,dv.version_no desc limit 1;
 if oldvalue is distinct from f.old_value then raise exception 'Stale review';end if;
 update public.extracted_values set approved=true,reviewed=true where extracted_value_id=e.extracted_value_id;
 update public.value_diffs set review_status='applied',reviewed_at=now(),reviewed_by='local-web' where diff_id=f.diff_id;
 return jsonb_build_object('review_status','applied');
end $$;
revoke all on function public.save_management_rules(jsonb),public.review_management_rules_diff(jsonb) from public,anon,authenticated;
grant execute on function public.save_management_rules(jsonb),public.review_management_rules_diff(jsonb) to service_role;
create or replace function public.web_workspace_snapshot(p jsonb default '{}')
returns jsonb language sql security invoker set search_path='' as $fn$
select jsonb_build_object(
 'cases',coalesce((select jsonb_agg(to_jsonb(c)) from public.cases c),'[]'),
 'units',coalesce((select jsonb_agg(to_jsonb(u)) from public.units u),'[]'),
 'buildings',coalesce((select jsonb_agg(to_jsonb(b)) from public.buildings b),'[]'),
 'documents',coalesce((select jsonb_agg(to_jsonb(d)) from public.documents d where document_type in ('registry','important_report','management_rules')),'[]'),
 'versions',coalesce((select jsonb_agg(to_jsonb(v)-'storage_path') from public.document_versions v join public.documents d using(document_id) where d.document_type in ('registry','important_report','management_rules')),'[]'),
 'values',coalesce((select jsonb_agg(to_jsonb(e)) from public.extracted_values e join public.document_versions v using(document_version_id) join public.documents d using(document_id) where d.document_type in ('registry','important_report','management_rules')),'[]'),
 'diffs',coalesce((select jsonb_agg(to_jsonb(f)) from public.value_diffs f join public.documents d using(document_id) where d.document_type in ('registry','important_report','management_rules')),'[]'),
 'imports',coalesce((select jsonb_agg(jsonb_build_object('document_version_id',r.document_version_id,'raw_json',r.raw_json,'created_at',r.created_at,'content_hash',r.content_hash)) from public.registry_imports r),'[]'));
$fn$;
