/* Public demo uses only the bundled fictional fixture; no backend calls. */
'use strict';
window.PublicDemo=(()=>{
 let state;
 const clone=x=>JSON.parse(JSON.stringify(x));
 async function request(path,body){
  if(!state){const response=await fetch('/demo.json',{credentials:'omit'});if(!response.ok)throw Error('デモを読み込めませんでした。');state=await response.json();}
  if(path==='/api/state'||path==='/api/refresh')return clone(state);
  if(path!=='/api/decision')throw Error('WEB版では準備中です。');
  const c=state.cases.find(c=>c.id===body.case_id),d=c?.diffs.find(d=>d.id===body.diff_id);
  if(!d||!['adopt','hold'].includes(body.action)||['applied','ignored'].includes(d.review_status))throw Error('差分の操作を確認してください。');
  if(body.action==='adopt'){
   if(!d.can_adopt)throw Error('原本確認が必要な項目です。');
   if(d.code==='current_owner_name')c.owner=d.new_value;
   c.confirmed_values[d.code]=clone(d.new_value);
  }
  d.review_status=body.action==='adopt'?'applied':'reviewed';
  c.diff_count=c.diffs.filter(d=>d.review_status==='unreviewed').length;
  c.updated_at=new Date().toISOString();
  return clone(state);
 }
 return {request};
})();
