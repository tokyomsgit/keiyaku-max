-- Run against the configured project. All test changes are rolled back.
begin;
do $test$
declare b uuid; u uuid; p jsonb; a jsonb; r jsonb; did uuid; blocked boolean;
begin
 insert into public.buildings(building_name) values ('Web regression synthetic') returning building_id into b;
 insert into public.units(building_id,house_number,management_fee) values(b,'__web_regression__',12000) returning unit_id into u;
 p:=jsonb_build_object('identity',jsonb_build_object('unit_id',u),'source',jsonb_build_object('file_hash',repeat('c',64),'original_filename','synthetic.pdf'),
   'source_type','seller_provided','status','provisional','import_key',repeat('d',64),
   'raw_json',jsonb_build_object('is_important_report',true,'fields',jsonb_build_object('management_fee',jsonb_build_object(
    'value',12000,'source_text','12000円','page_no',1,'confidence',0.99,'needs_review',false,'value_as_of_date','2026-01-31'))));
 a:=public.save_important_report(p);
 perform public.approve_important_report(jsonb_build_object('document_version_id',a->>'document_version_id','field_codes',jsonb_build_array('management_fee'),'reviewed_by','regression'));
 p:=jsonb_set(p,'{raw_json,fields,management_fee,value}','13500');
 p:=jsonb_set(p,'{raw_json,fields,management_fee,source_text}','"13500円"');
 p:=jsonb_set(p,'{import_key}',to_jsonb(repeat('e',64)));
 r:=public.save_important_report(p);assert r->>'diffs_created'='1';
 select diff_id into did from public.value_diffs where new_version_id=(r->>'document_version_id')::uuid;
 perform public.web_review_diff(jsonb_build_object('unit_id',u,'diff_id',did,'action','hold'));
 assert (select review_status='reviewed' from public.value_diffs where diff_id=did);
 assert (select management_fee=12000 from public.units where unit_id=u);
 update public.units set management_fee=13000 where unit_id=u;
 blocked:=false;
 begin perform public.web_review_diff(jsonb_build_object('unit_id',u,'diff_id',did,'action','adopt'));
 exception when others then blocked:=true; end;
 assert blocked;
 update public.units set management_fee=12000 where unit_id=u;
 update public.extracted_values set confidence=0.5 where document_version_id=(r->>'document_version_id')::uuid;
 blocked:=false;
 begin perform public.web_review_diff(jsonb_build_object('unit_id',u,'diff_id',did,'action','adopt'));
 exception when others then blocked:=true; end;
 assert blocked;
 update public.extracted_values set confidence=0.99 where document_version_id=(r->>'document_version_id')::uuid;
 perform public.web_review_diff(jsonb_build_object('unit_id',u,'diff_id',did,'action','adopt'));
 assert (select management_fee=13500 from public.units where unit_id=u);
 assert (select review_status='applied' from public.value_diffs where diff_id=did);
 assert (public.web_review_diff(jsonb_build_object('unit_id',u,'diff_id',did,'action','adopt'))->>'reused')='true';
 assert not has_function_privilege('anon','public.web_review_diff(jsonb)','EXECUTE');
 assert not has_function_privilege('authenticated','public.web_workspace_snapshot(jsonb)','EXECUTE');
end $test$;
select 'PASS: hold, conflict, low confidence rejection, adoption, idempotence, service-only; all rolled back' as result;
rollback;
