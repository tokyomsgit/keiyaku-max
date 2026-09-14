alter table public.cases add column if not exists purchase_values jsonb;

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


create or replace function public.web_register_registry_case(p jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare m jsonb; b jsonb:=p->'building'; u jsonb:=p->'unit'; result jsonb; prior public.units;
 bid uuid;uid uuid;cid uuid;did uuid;vid uuid;firstvid uuid;oldvid uuid; doc jsonb;item jsonb;f jsonb;
 created_b boolean:=false;created_u boolean:=false;created_c boolean:=false;
 dtype text:=case when p->'raw_json'->>'format'='normalized_purchase_v1' then 'purchase_important_explanation' else 'registry' end;
 count_docs integer:=0;count_values integer:=0;count_diffs integer:=0;ids jsonb:='[]';n integer;
begin
 if coalesce(p->>'request_key','') !~ '^[a-f0-9]{64}$' or coalesce(p->'raw_json'->>'format','') not in ('normalized_registry_v1','normalized_purchase_v1')
  or coalesce(jsonb_array_length(p->'documents'),0) not between 1 and 12 then raise exception 'Invalid registration';end if;
 perform pg_catalog.pg_advisory_xact_lock(710904,1);
 select r.result into result from public.registry_imports r where content_hash=p->>'request_key';
 if found then return result||jsonb_build_object('reused',true);end if;
 m:=public.web_registry_match(p);
 if m->>'status' not in ('new','existing') or m is distinct from p->'expected_match' then
  return jsonb_build_object('match_changed',true,'match',m);
 end if;
 bid:=(m->>'building_id')::uuid;uid:=(m->>'unit_id')::uuid;
 if bid is null then
  insert into public.buildings(building_name,registry_location,property_type,building_structure,land_lots,floor_areas)
   values(b->>'building_name',b->>'registry_location',b->>'property_type',b->>'building_structure',coalesce(b->'land_lots','[]'),coalesce(b->'floor_areas','[]')) returning building_id into bid;
  created_b:=true;
 end if;
 if uid is null then
  insert into public.units(building_id,house_number,unit_name,unit_type,unit_structure,unit_floor,registered_area,built_date,
   current_owner_name,current_owner_address,has_land_right,land_right_type,land_right_numerator,land_right_denominator,active_mortgages)
  values(bid,u->>'house_number',u->>'unit_name',u->>'unit_type',u->>'unit_structure',u->>'unit_floor',(u->>'registered_area')::numeric,(u->>'built_date')::date,
   u->>'current_owner_name',u->>'current_owner_address',(u->>'has_land_right')::boolean,u->>'land_right_type',(u->>'land_right_numerator')::numeric,
   (u->>'land_right_denominator')::numeric,coalesce(u->'active_mortgages','[]')) returning unit_id into uid;
  created_u:=true;
 else select * into prior from public.units where unit_id=uid for update;
 end if;
 if p->>'case_mode'='resume' then
  select case_id into cid from public.cases where case_id=(p->>'resume_case_id')::uuid and unit_id=uid;
  if cid is null then raise exception 'Invalid case';end if;
 elsif p->>'case_mode'='new' then
  insert into public.cases(unit_id,case_status) values(uid,'draft') returning case_id into cid;created_c:=true;
 else raise exception 'Invalid case mode';end if;
 for doc in select * from jsonb_array_elements(p->'documents') loop
  if coalesce(doc->>'file_hash','') !~ '^[a-f0-9]{64}$' then raise exception 'Invalid source hash';end if;
  select v.document_version_id,v.document_id into vid,did from public.document_versions v join public.documents d using(document_id)
   where d.unit_id=uid and d.document_type=dtype and v.file_hash=doc->>'file_hash' order by v.uploaded_at limit 1;
  if vid is null then
   insert into public.documents(document_type,building_id,unit_id,case_id,title) values(dtype,bid,uid,cid,doc->>'original_filename') returning document_id into did;
   insert into public.document_versions(document_id,version_no,source_type,status,original_filename,file_hash,storage_path)
    values(did,1,case when dtype='registry' then 'seller_provided' else 'historical_purchase_document' end,'provisional',doc->>'original_filename',doc->>'file_hash',doc->>'storage_path') returning document_version_id into vid;
   count_docs:=count_docs+1;
   for item in select * from jsonb_array_elements(doc->'values') loop
    insert into public.extracted_values(document_version_id,field_code,value,confidence,source_text,page_no,value_as_of_date,registry_provenance,source_label,source_section)
     values(vid,item->>'field_code',item->'value',(item->>'confidence')::numeric,item->>'source_text',(item->>'page_no')::integer,
      (item->>'value_as_of_date')::date,item->'provenance',item->>'source_label',item->>'source_section');count_values:=count_values+1;
   end loop;
  end if;
  firstvid:=coalesce(firstvid,vid);ids:=ids||jsonb_build_array(vid);
  if not created_u and dtype='registry' and not exists(select 1 from public.cases where case_id=cid and purchase_values is not null) then
   for f in select * from jsonb_array_elements(p->'fields') loop
    if f->>'field_code' not in ('current_owner_name','current_owner_address','active_mortgages','registered_area','land_right_type','land_right_numerator','land_right_denominator')
      or coalesce((f->>'needs_review')::boolean,true) or not u ? (f->>'field_code') then continue;end if;
    if to_jsonb(prior)->(f->>'field_code') is distinct from f->'value' and exists(select 1 from public.extracted_values where document_version_id=vid and field_code=f->>'field_code' and value=f->'value')
      and not exists(select 1 from public.value_diffs q join public.documents d using(document_id) where d.unit_id=uid and q.field_code=f->>'field_code'
       and q.old_value is not distinct from to_jsonb(prior)->(f->>'field_code') and q.new_value is not distinct from f->'value') then
     select e.document_version_id into oldvid from public.extracted_values e join public.document_versions v using(document_version_id) join public.documents d using(document_id)
      where d.unit_id=uid and e.field_code=f->>'field_code' and e.value is not distinct from to_jsonb(prior)->(f->>'field_code') order by e.approved desc,e.created_at desc limit 1;
     insert into public.value_diffs(document_id,old_version_id,new_version_id,field_code,old_value,new_value,review_status,affected_field)
      values(did,oldvid,vid,f->>'field_code',to_jsonb(prior)->(f->>'field_code'),f->'value','unreviewed','units.'||(f->>'field_code'));count_diffs:=count_diffs+1;
    end if;
   end loop;
  end if;
 end loop;
 result:=jsonb_build_object('building_id',bid,'unit_id',uid,'case_id',cid,'building_created',created_b,'unit_created',created_u,'case_created',created_c,
  'documents_created',count_docs,'values_created',count_values,'diffs_created',count_diffs,'version_ids',ids,'reused',false);
 insert into public.registry_imports(content_hash,document_version_id,raw_json,result) values(p->>'request_key',firstvid,p->'raw_json',result);
 if dtype='purchase_important_explanation' then perform public.web_initialize_purchase(cid,ids);end if;
 perform public.web_sync_purchase_diffs(jsonb_build_object('case_id',cid));
 return result;
end $$;
revoke all on function public.registry_match_text(text),public.registry_parcels(jsonb),public.web_registry_match(jsonb),public.web_register_registry_case(jsonb) from public,anon,authenticated;
grant execute on function public.registry_match_text(text),public.registry_parcels(jsonb),public.web_registry_match(jsonb),public.web_register_registry_case(jsonb) to service_role;


create or replace function public.web_workspace_snapshot(p jsonb default '{}')
returns jsonb language sql security invoker set search_path='' as $fn$
select jsonb_build_object(
 'cases',coalesce((select jsonb_agg(to_jsonb(c)) from public.cases c),'[]'),
 'units',coalesce((select jsonb_agg(to_jsonb(u)) from public.units u),'[]'),
 'buildings',coalesce((select jsonb_agg(to_jsonb(b)) from public.buildings b),'[]'),
 'documents',coalesce((select jsonb_agg(to_jsonb(d)) from public.documents d where document_type in ('registry','important_report','management_rules','purchase_important_explanation')),'[]'),
 'versions',coalesce((select jsonb_agg(to_jsonb(v)-'storage_path') from public.document_versions v join public.documents d using(document_id) where d.document_type in ('registry','important_report','management_rules','purchase_important_explanation')),'[]'),
 'values',coalesce((select jsonb_agg(to_jsonb(e)) from public.extracted_values e join public.document_versions v using(document_version_id) join public.documents d using(document_id) where d.document_type in ('registry','important_report','management_rules','purchase_important_explanation')),'[]'),
 'diffs',coalesce((select jsonb_agg(to_jsonb(f)) from public.value_diffs f join public.documents d using(document_id) where d.document_type in ('registry','important_report','management_rules','purchase_important_explanation')),'[]'),
 'imports',coalesce((select jsonb_agg(jsonb_build_object('document_version_id',r.document_version_id,'raw_json',r.raw_json,'created_at',r.created_at,'content_hash',r.content_hash)) from public.registry_imports r),'[]'));
$fn$;
