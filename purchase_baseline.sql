-- Case-local adopted evidence IDs keep historical documents immutable.
create or replace function public.purchase_source(code text) returns text
language sql immutable security invoker set search_path='' as $$
 select case when code in ('building_name','registry_location','building_structure','floor_areas','house_number','unit_name','unit_type','unit_structure','unit_floor','registered_area','built_date','current_owner_name','current_owner_address','land_lots','has_land_right','land_right_type','land_right_numerator','land_right_denominator','active_mortgages') then 'registry'
 when code in ('pet_restrictions','office_use_allowed','instrument_restrictions','renovation_restrictions','leasing_restrictions','parking_rules','voting_rights_rule','rules_effective_date','unit_use_restrictions','balcony_exclusive_use','private_garden_rules','door_window_exclusive_use','management_association_name','related_rules') then 'management_rules'
 else 'important_report' end
$$;

create or replace function public.web_initialize_purchase(cid uuid, ids jsonb) returns void
language plpgsql security invoker set search_path='' as $$
declare chosen jsonb; uid uuid;
begin
 select unit_id into uid from public.cases where case_id=cid and purchase_values is null for update;
 if uid is null then return;end if;
 select coalesce(jsonb_object_agg(field_code,extracted_value_id),'{}') into chosen from (
 select distinct on(e.field_code) e.field_code,e.extracted_value_id
 from public.extracted_values e join public.document_versions v using(document_version_id) join public.documents d using(document_id)
 where d.unit_id=uid and (ids ? v.document_version_id::text or e.approved)
 and e.value is not null and e.value<>'null' and e.confidence>=.85 and e.page_no>0 and nullif(e.source_text,'') is not null
 and not coalesce((e.registry_provenance->>'needs_review')::boolean,false)
 and not coalesce((v.important_raw_json->'fields'->e.field_code->>'needs_review')::boolean,false)
 order by e.field_code,e.approved desc,e.created_at desc) q;
 update public.cases set purchase_values=chosen,updated_at=now() where case_id=cid;
end $$;

create or replace function public.web_sync_purchase_diffs(p jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare c public.cases; bid uuid; e record; oldv public.extracted_values; n integer:=0;
begin
 perform pg_catalog.pg_advisory_xact_lock(710904,1);
 select * into c from public.cases where case_id=(p->>'case_id')::uuid for update;
 if c.purchase_values is null then return jsonb_build_object('diffs_created',0);end if;
 select building_id into bid from public.units where unit_id=c.unit_id;
 for e in
  select distinct on(ev.field_code) ev.*,dv.uploaded_at,doc.document_id,doc.document_type
  from public.extracted_values ev join public.document_versions dv using(document_version_id) join public.documents doc using(document_id)
  where (doc.unit_id=c.unit_id or (doc.unit_id is null and doc.building_id=bid and doc.document_type='management_rules'))
   and doc.document_type=public.purchase_source(ev.field_code) and ev.value is not null and ev.value<>'null'
  order by ev.field_code,dv.uploaded_at desc,ev.created_at desc,ev.extracted_value_id
 loop
  select * into oldv from public.extracted_values where extracted_value_id=(c.purchase_values->>e.field_code)::uuid;
  if e.value is not distinct from oldv.value then continue;end if;
  if oldv.value_as_of_date is not null and e.value_as_of_date is not null and e.value_as_of_date<oldv.value_as_of_date then continue;end if;
  if not exists(select 1 from public.value_diffs where affected_field='purchase:'||c.case_id::text and field_code=e.field_code
     and new_version_id=e.document_version_id and old_value is not distinct from oldv.value) then
   insert into public.value_diffs(document_id,old_version_id,new_version_id,field_code,old_value,new_value,review_status,affected_field)
    values(e.document_id,oldv.document_version_id,e.document_version_id,e.field_code,oldv.value,e.value,'unreviewed','purchase:'||c.case_id::text);
   n:=n+1;
  end if;
 end loop;
 return jsonb_build_object('diffs_created',n);
end $$;

create or replace function public.web_review_purchase_diff(p jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare c public.cases; f public.value_diffs; e public.extracted_values; v public.document_versions; d public.documents; oldv public.extracted_values; bid uuid;
begin
 perform pg_catalog.pg_advisory_xact_lock(710904,1);
 select * into c from public.cases where case_id=(p->>'case_id')::uuid for update;
 select * into f from public.value_diffs where diff_id=(p->>'diff_id')::uuid and affected_field='purchase:'||c.case_id::text for update;
 if c.purchase_values is null or f.diff_id is null then raise exception 'Case mismatch';end if;
 if f.review_status='applied' then return jsonb_build_object('reused',true);end if;
 if f.review_status not in ('unreviewed','reviewed') then raise exception 'Not reviewable';end if;
 if p->>'action'='hold' then
  update public.value_diffs set review_status='reviewed',reviewed_at=now(),reviewed_by='local-web' where diff_id=f.diff_id;
  return jsonb_build_object('review_status','reviewed');
 end if;
 if p->>'action' is distinct from 'adopt' then raise exception 'Invalid action';end if;
 select * into e from public.extracted_values where document_version_id=f.new_version_id and field_code=f.field_code;
 select * into v from public.document_versions where document_version_id=e.document_version_id;
 select * into d from public.documents where document_id=v.document_id;
 select building_id into bid from public.units where unit_id=c.unit_id;
 if not (d.unit_id=c.unit_id or (d.unit_id is null and d.building_id=bid and d.document_type='management_rules'))
  or d.document_type is distinct from public.purchase_source(f.field_code) then raise exception 'Source mismatch';end if;
 if e.value is distinct from f.new_value or e.value is null or e.value='null' or e.confidence is null or e.confidence<.85 or e.page_no is null or e.page_no<1 or nullif(e.source_text,'') is null
  or coalesce((e.registry_provenance->>'needs_review')::boolean,false)
  or coalesce((v.important_raw_json->'fields'->e.field_code->>'needs_review')::boolean,false)
  or coalesce((v.management_rules_raw_json->'fields'->e.field_code->>'needs_review')::boolean,false) then raise exception 'Evidence review required';end if;
 select * into oldv from public.extracted_values where extracted_value_id=(c.purchase_values->>e.field_code)::uuid;
 if oldv.value is distinct from f.old_value or oldv.document_version_id is distinct from f.old_version_id then raise exception 'Review is stale';end if;
 if oldv.value_as_of_date is not null and e.value_as_of_date is not null and e.value_as_of_date<oldv.value_as_of_date then raise exception 'Older source';end if;
 update public.cases set purchase_values=purchase_values||jsonb_build_object(e.field_code,e.extracted_value_id),updated_at=now() where case_id=c.case_id;
 update public.value_diffs set review_status='applied',reviewed_at=now(),reviewed_by='local-web' where diff_id=f.diff_id;
 return jsonb_build_object('review_status','applied');
end $$;
revoke all on function public.purchase_source(text),public.web_initialize_purchase(uuid,jsonb),public.web_sync_purchase_diffs(jsonb),public.web_review_purchase_diff(jsonb) from public,anon,authenticated;
grant execute on function public.purchase_source(text),public.web_initialize_purchase(uuid,jsonb),public.web_sync_purchase_diffs(jsonb),public.web_review_purchase_diff(jsonb) to service_role;
