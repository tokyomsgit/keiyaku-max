-- Case registration is separate from the legacy single-document Claude importer.
alter table public.extracted_values add column if not exists registry_provenance jsonb;

create or replace function public.registry_match_text(v text) returns text
language sql immutable security invoker set search_path='' as $$
 select regexp_replace(coalesce(v,''),'[[:space:]・]+','','g')
$$;
create or replace function public.registry_parcels(v jsonb) returns jsonb
language sql immutable security invoker set search_path='' as $$
 select coalesce(jsonb_agg(x order by x::text),'[]'::jsonb) from
 (select distinct jsonb_build_array(public.registry_match_text(i->>'location'),public.registry_match_text(i->>'lot_number')) x
 from jsonb_array_elements(coalesce(v,'[]'::jsonb)) i) s
$$;

create or replace function public.web_registry_match(p jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare b jsonb:=p->'building';u jsonb:=p->'unit'; bs uuid[]; us uuid[]; bid uuid; uid uuid;
 candidates jsonb:='[]'; cs jsonb:='[]'; state text:='new'; reason text:='';
begin
 if coalesce(b->>'property_type','') not in ('condominium_land_right','condominium_no_land_right','leasehold_condominium') then
  return jsonb_build_object('status','blocked','reason','物件種別が対象外です。','candidates','[]'::jsonb,'cases','[]'::jsonb);
 end if;
 select array_agg(unit_id) into us from public.units where nullif(u->>'house_number','') is not null and house_number=u->>'house_number';
 if coalesce(cardinality(us),0)=0 then
  select array_agg(building_id) into bs from public.buildings x where
   (nullif(b->>'registry_location','') is not null and public.registry_match_text(x.registry_location)=public.registry_match_text(b->>'registry_location') and
    ((public.registry_parcels(b->'land_lots')<>'[]' and public.registry_parcels(x.land_lots)=public.registry_parcels(b->'land_lots')) or
     (nullif(b->>'building_name','') is not null and public.registry_match_text(x.building_name)=public.registry_match_text(b->>'building_name')))) or
   (public.registry_parcels(b->'land_lots')<>'[]' and public.registry_parcels(x.land_lots)=public.registry_parcels(b->'land_lots') and
    nullif(b->>'building_name','') is not null and public.registry_match_text(x.building_name)=public.registry_match_text(b->>'building_name'));
  select array_agg(unit_id) into us from public.units x where building_id=any(bs) and nullif(u->>'unit_name','') is not null
   and regexp_replace(public.registry_match_text(x.unit_name),'号室$','')=regexp_replace(public.registry_match_text(u->>'unit_name'),'号室$','');
 end if;
 if coalesce(cardinality(us),0)>1 then state:='ambiguous';reason:='住戸候補が複数あります。自動登録しません。';
 elsif cardinality(us)=1 then
  uid:=us[1];select building_id into bid from public.units where unit_id=uid;state:='existing';
 elsif coalesce(cardinality(bs),0)>1 then state:='ambiguous';reason:='一棟候補が複数あります。自動登録しません。';
 else
  bid:=bs[1];
  if nullif(u->>'house_number','') is null or nullif(u->>'unit_name','') is null or nullif(b->>'registry_location','') is null
   or public.registry_parcels(b->'land_lots')='[]' or exists(select 1 from jsonb_array_elements(b->'land_lots') x where nullif(x->>'location','') is null or nullif(x->>'lot_number','') is null) then
   state:='incomplete';reason:='新規登録に必要な家屋番号・号室・所在・土地の対応を確認してください。';
  end if;
 end if;
 if us is not null then
  select coalesce(jsonb_agg(jsonb_build_object('unit_id',x.unit_id,'building_id',x.building_id,'building_name',y.building_name,
    'unit_name',x.unit_name,'house_number',x.house_number,'registry_location',y.registry_location,'current_owner_name',x.current_owner_name,
    'updated_at',x.updated_at) order by x.unit_id),'[]') into candidates from public.units x join public.buildings y using(building_id) where x.unit_id=any(us);
 elsif bs is not null then
  select coalesce(jsonb_agg(jsonb_build_object('building_id',x.building_id,'building_name',x.building_name,'registry_location',x.registry_location,'updated_at',x.updated_at) order by x.building_id),'[]') into candidates from public.buildings x where x.building_id=any(bs);
 end if;
 if uid is not null then select coalesce(jsonb_agg(jsonb_build_object('case_id',case_id,'case_status',case_status,'updated_at',updated_at) order by created_at),'[]') into cs from public.cases where unit_id=uid; end if;
 return jsonb_build_object('status',state,'reason',reason,'building_id',bid,'unit_id',uid,'candidates',candidates,'cases',cs);
end $$;

create or replace function public.web_register_registry_case(p jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare m jsonb; b jsonb:=p->'building'; u jsonb:=p->'unit'; result jsonb; prior public.units;
 bid uuid;uid uuid;cid uuid;did uuid;vid uuid;firstvid uuid;oldvid uuid; doc jsonb;item jsonb;f jsonb;
 created_b boolean:=false;created_u boolean:=false;created_c boolean:=false;
 count_docs integer:=0;count_values integer:=0;count_diffs integer:=0;ids jsonb:='[]';n integer;
begin
 if coalesce(p->>'request_key','') !~ '^[a-f0-9]{64}$' or p->'raw_json'->>'format' is distinct from 'normalized_registry_v1'
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
   where d.unit_id=uid and d.document_type='registry' and v.file_hash=doc->>'file_hash' order by v.uploaded_at limit 1;
  if vid is null then
   insert into public.documents(document_type,building_id,unit_id,case_id,title) values('registry',bid,uid,cid,doc->>'original_filename') returning document_id into did;
   insert into public.document_versions(document_id,version_no,source_type,status,original_filename,file_hash,storage_path)
    values(did,1,'seller_provided','provisional',doc->>'original_filename',doc->>'file_hash',doc->>'storage_path') returning document_version_id into vid;
   count_docs:=count_docs+1;
   for item in select * from jsonb_array_elements(doc->'values') loop
    insert into public.extracted_values(document_version_id,field_code,value,confidence,source_text,page_no,value_as_of_date,registry_provenance)
     values(vid,item->>'field_code',item->'value',(item->>'confidence')::numeric,item->>'source_text',(item->>'page_no')::integer,
      (item->>'value_as_of_date')::date,item->'provenance');count_values:=count_values+1;
   end loop;
  end if;
  firstvid:=coalesce(firstvid,vid);ids:=ids||jsonb_build_array(vid);
  if not created_u then
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
 return result;
end $$;
revoke all on function public.registry_match_text(text),public.registry_parcels(jsonb),public.web_registry_match(jsonb),public.web_register_registry_case(jsonb) from public,anon,authenticated;
grant execute on function public.registry_match_text(text),public.registry_parcels(jsonb),public.web_registry_match(jsonb),public.web_register_registry_case(jsonb) to service_role;
