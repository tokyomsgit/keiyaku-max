create or replace function public.web_workspace_snapshot(p jsonb default '{}')
returns jsonb language sql security invoker set search_path='' as $fn$
select jsonb_build_object(
 'cases',coalesce((select jsonb_agg(to_jsonb(c)) from public.cases c),'[]'),
 'units',coalesce((select jsonb_agg(to_jsonb(u)) from public.units u),'[]'),
 'buildings',coalesce((select jsonb_agg(to_jsonb(b)) from public.buildings b),'[]'),
 'documents',coalesce((select jsonb_agg(to_jsonb(d)) from public.documents d where document_type in ('registry','important_report')),'[]'),
 'versions',coalesce((select jsonb_agg(to_jsonb(v)-'storage_path') from public.document_versions v join public.documents d using(document_id) where d.document_type in ('registry','important_report')),'[]'),
 'values',coalesce((select jsonb_agg(to_jsonb(e)) from public.extracted_values e join public.document_versions v using(document_version_id) join public.documents d using(document_id) where d.document_type in ('registry','important_report')),'[]'),
 'diffs',coalesce((select jsonb_agg(to_jsonb(f)) from public.value_diffs f join public.documents d using(document_id) where d.document_type in ('registry','important_report')),'[]'),
 'imports',coalesce((select jsonb_agg(jsonb_build_object('document_version_id',r.document_version_id,'raw_json',r.raw_json,'created_at',r.created_at,'content_hash',r.content_hash)) from public.registry_imports r),'[]'));
$fn$;

create or replace function public.web_review_diff(p jsonb)
returns jsonb language plpgsql security invoker set search_path='' as $fn$
declare f public.value_diffs; d public.documents; e public.extracted_values; v public.document_versions;
 target_table text; target_id uuid; key_column text; current_value jsonb; column_exists boolean;
begin
 perform pg_catalog.pg_advisory_xact_lock(710904,1);
 perform pg_catalog.pg_advisory_xact_lock(710904,2);
 select * into f from public.value_diffs where diff_id=(p->>'diff_id')::uuid for update;
 if not found then raise exception 'Unknown diff'; end if;
 select * into d from public.documents where document_id=f.document_id;
 if d.unit_id is null or d.unit_id is distinct from (p->>'unit_id')::uuid then raise exception 'Unit mismatch'; end if;
 if f.review_status='applied' then return jsonb_build_object('review_status','applied','reused',true); end if;
 if f.review_status not in ('unreviewed','reviewed') then raise exception 'Not reviewable'; end if;
 if p->>'action'='hold' then
   update public.value_diffs set review_status='reviewed',reviewed_at=now(),reviewed_by='local-web' where diff_id=f.diff_id;
   return jsonb_build_object('review_status','reviewed');
 end if;
 if p->>'action' is distinct from 'adopt' or f.new_value is null or f.new_value='null'::jsonb then raise exception 'Invalid decision'; end if;
 select * into e from public.extracted_values where document_version_id=f.new_version_id and field_code=f.field_code;
 select * into v from public.document_versions where document_version_id=f.new_version_id;
 if e.value is distinct from f.new_value or e.confidence is null or e.confidence<0.85 or nullif(e.source_text,'') is null or e.page_no is null or e.page_no<1
    or coalesce((to_jsonb(e)->'registry_provenance'->>'needs_review')::boolean,false)
    or coalesce((v.important_raw_json->'fields'->f.field_code->>'needs_review')::boolean,false) then raise exception 'Evidence review required'; end if;
 select case entity_level when 'unit' then 'units' when 'building' then 'buildings' end into target_table from public.field_master where field_code=f.field_code and is_active;
 if target_table is null then raise exception 'Unsupported field'; end if;
 key_column:=case target_table when 'units' then 'unit_id' else 'building_id' end;
 target_id:=case target_table when 'units' then d.unit_id else d.building_id end;
 if target_id is null then raise exception 'Missing target'; end if;
 select exists(select 1 from information_schema.columns where table_schema='public' and table_name=target_table and column_name=f.field_code) into column_exists;
 if column_exists then
   execute format('select to_jsonb(t)->$1 from public.%I t where %I=$2 for update',target_table,key_column) into current_value using f.field_code,target_id;
   if current_value is null then raise exception 'Missing master'; end if;
   if current_value is distinct from f.old_value and (d.document_type='registry' or current_value is distinct from 'null'::jsonb) then raise exception 'Master changed; reload'; end if;
 end if;
 if d.document_type='important_report' then
   perform public.approve_important_report(jsonb_build_object('document_version_id',f.new_version_id,'field_codes',jsonb_build_array(f.field_code),'reviewed_by','local-web'));
 elsif d.document_type='registry' then
   if f.field_code not in ('current_owner_name','current_owner_address','active_mortgages','registered_area','land_right_type','land_right_numerator','land_right_denominator') then raise exception 'Unsupported registry diff'; end if;
   update public.extracted_values set reviewed=true,approved=true where extracted_value_id=e.extracted_value_id;
 else raise exception 'Unsupported document'; end if;
 if column_exists then
   execute format('update public.%I set %I=(select x.%I from jsonb_populate_record(null::public.%I,$1) x),updated_at=now() where %I=$2',target_table,f.field_code,f.field_code,target_table,key_column)
     using jsonb_build_object(f.field_code,f.new_value),target_id;
 end if;
 update public.value_diffs set review_status='applied',reviewed_at=now(),reviewed_by='local-web' where diff_id=f.diff_id;
 return jsonb_build_object('review_status','applied');
end $fn$;
revoke all on function public.web_workspace_snapshot(jsonb),public.web_review_diff(jsonb) from public,anon,authenticated;
grant execute on function public.web_workspace_snapshot(jsonb),public.web_review_diff(jsonb) to service_role;
