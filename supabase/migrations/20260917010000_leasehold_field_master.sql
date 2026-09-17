-- Registry registration writes these codes (web_registration.PATHS); without them the
-- extracted_values foreign key rejects every new registry registration.
insert into public.field_master(field_code,label_ja,entity_level,data_type,primary_source,diff_enabled,is_active,notes) values
 ('leasehold_area','借地対象面積','unit','number','謄本/借地資料',true,true,'借地権'),
 ('leasehold_ground_rent_monthly','地代（月額）','unit','number','借地資料',true,true,'借地権'),
 ('leasehold_ground_rent_unit','地代（3.3㎡当たり月額）','unit','number','謄本/借地資料',true,true,'借地権。住戸の地代へ換算しない'),
 ('leasehold_law_type','借地権の法区分','unit','text','謄本/借地資料',true,true,'借地権'),
 ('leasehold_period_start','借地期間開始','unit','date','謄本/借地資料',true,true,'借地権'),
 ('leasehold_period_end','借地期間終了','unit','date','謄本/借地資料',true,true,'借地権'),
 ('leasehold_period_years','借地期間','unit','number','謄本/借地資料',true,true,'借地権'),
 ('leasehold_assignment_consent','譲渡承諾の要否','unit','boolean','謄本/借地資料',true,true,'借地権')
on conflict (field_code) do nothing;
