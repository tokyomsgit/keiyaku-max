'use strict';
const API='https://ugnkhzjswjqszmzzpelz.supabase.co/functions/v1/keiyaku-api';
const root=document.querySelector('#live-app');
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const display=v=>v===null||v===undefined||v===''?'未取得':typeof v==='number'?v.toLocaleString('ja-JP'):String(v);
let liveState=null;

async function request(action,options={}){
  const token=window.KeiyakuAuth?.token();
  if(!token)throw Error('ログインし直してください。');
  const response=await fetch(`${API}?action=${action}`,{...options,headers:{...(options.headers||{}),Authorization:`Bearer ${token}`}});
  if(!response.ok){let data={};try{data=await response.json();}catch{}throw Error(data.error||'処理に失敗しました。');}
  return response;
}

function list(){
  const cases=liveState?.cases||[];
  root.innerHTML=`<nav class="steps" aria-label="契約書作成の工程"><a>① 資料</a><a>② 要確認</a><a class="active" aria-current="step">③ 契約書生成</a></nav><div class="top"><div><h1>契約書を生成</h1><p>Supabaseに保存済みの物件データを、本番Excelひな形へ反映します。</p></div><div class="actions"><button id="create" class="primary">新しい契約書を作成</button><button id="refresh">最新情報に更新</button></div></div>${cases.length?`<div class="card table-scroll"><table><thead><tr><th>物件名</th><th>号室</th><th>所在地</th><th>要確認</th><th>操作</th></tr></thead><tbody>${cases.map(c=>`<tr class="case-row"><td><strong>${esc(c.building_name)}</strong></td><td>${esc(c.unit_name)}</td><td>${esc(c.address)}</td><td>${c.unresolved?`<span class="pill warn">${c.unresolved}件</span>`:'<span class="pill">確認済み</span>'}</td><td><button class="primary" data-open="${esc(c.id)}">内容を確認して生成</button></td></tr>`).join('')}</tbody></table></div>`:'<div class="card empty"><p>生成できる物件データがありません。</p><p>「新しい契約書を作成」から登録してください。</p></div>'}`;
  document.querySelector('#refresh').onclick=load;
  document.querySelector('#create').onclick=createForm;
  root.querySelectorAll('[data-open]').forEach(button=>button.onclick=()=>detail(button.dataset.open));
}

function createForm(){root.innerHTML=`<nav class="steps"><a class="active">① 資料</a><a>② 要確認</a><a>③ 契約書生成</a></nav><p><button id="back">← 案件一覧へ</button></p><div class="card"><h1>新しい契約書を作成</h1><p>誤物件への紐付けを防ぐため、登記上の識別情報を入力してください。</p><div class="facts new-case-form"><label>物件名<input id="building-name" required></label><label>号室<input id="unit-name" required></label><label>登記上の所在<input id="registry-location" required></label><label>家屋番号<input id="house-number" required></label><label>住居表示（任意）<input id="display-address"></label></div><div class="actions"><button id="save-new" class="primary">この物件で作成を始める</button></div><p id="status" role="status"></p></div>`;document.querySelector('#back').onclick=list;document.querySelector('#save-new').onclick=createNew;}

async function createNew(){const button=document.querySelector('#save-new'),status=document.querySelector('#status');button.disabled=true;status.textContent='登録しています…';try{const body={building_name:document.querySelector('#building-name').value,unit_name:document.querySelector('#unit-name').value,registry_location:document.querySelector('#registry-location').value,house_number:document.querySelector('#house-number').value,display_address:document.querySelector('#display-address').value};const result=await (await request('create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();liveState=result.state;detail(result.case_id);}catch(error){status.textContent=error.message;button.disabled=false;}}

function detail(id){
  const item=liveState.cases.find(c=>c.id===id);if(!item)return list();
  const missing=item.fields.filter(f=>f.value===null||f.value===undefined||f.value==='').length;
  root.innerHTML=`<nav class="steps"><a>① 資料</a><a class="${item.unresolved?'active':''}">② 要確認</a><a class="${item.unresolved?'':'active'}">③ 契約書生成</a></nav><p><button id="back">← 物件一覧へ</button></p>${item.reviews?.map(review=>`<div class="card"><div class="review-heading"><div><h2>${esc(review.label)}</h2><p>新旧どちらを使うか選んでください。</p></div><span class="review-remaining">要確認</span></div><div class="review-choices"><button data-decision="old" data-diff="${esc(review.diff_id)}"><span>現在の値を使う</span><strong>${esc(display(review.old_value))}</strong></button><button class="primary" data-decision="new" data-diff="${esc(review.diff_id)}"><span>新しい資料を使う</span><strong>${esc(display(review.new_value))}</strong></button></div></div>`).join('')||''}<div class="card"><div class="review-heading"><div><h2>${esc(item.building_name)} ${esc(item.unit_name)}</h2><p>Excelへ反映する主要情報</p></div>${item.unresolved?`<span class="review-remaining">あと${item.unresolved}件確認</span>`:'<span class="review-complete">✓ 差分確認済み</span>'}</div><dl class="facts">${item.fields.map(f=>`<div><dt>${esc(f.label)}</dt><dd>${esc(display(f.value))}</dd></div>`).join('')}</dl>${missing?`<p class="muted">未取得：${missing}項目。未取得欄は空欄のまま生成します。</p>`:''}${item.unresolved?'<p class="upload-warning">確認が必要な差分を解消すると生成できます。</p>':'<p class="success">契約書を生成できます。</p>'}<div class="actions"><button id="generate" class="primary" ${item.unresolved?'disabled':''}>契約書Excelを生成</button></div><p id="status" role="status"></p></div>`;
  document.querySelector('#back').onclick=list;
  document.querySelector('#generate').onclick=()=>generate(item);
  root.querySelectorAll('[data-decision]').forEach(button=>button.onclick=()=>decide(item,button));
}

async function decide(item,button){button.disabled=true;try{liveState=await (await request('decision',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({case_id:item.id,diff_id:button.dataset.diff,choice:button.dataset.decision})})).json();detail(item.id);}catch(error){button.disabled=false;alert(error.message);}}

async function generate(item){
  const button=document.querySelector('#generate'),status=document.querySelector('#status');button.disabled=true;button.textContent='契約書作成中…';status.textContent='本番ひな形へ反映しています。';
  try{
    const response=await request('generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({case_id:item.id})});
    const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');
    link.href=url;link.download=`契約書_${item.building_name}_${item.unit_name}.xlsm`;link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);
    status.innerHTML='✓ 契約書を作成しました。ダウンロードしたExcelを原本と照合してください。';
  }catch(error){status.textContent=error.message;button.disabled=false;}finally{button.textContent='契約書Excelを生成';}
}

async function load(){root.innerHTML='<div class="card"><p>物件データを読み込んでいます…</p></div>';try{liveState=await (await request('state')).json();list();}catch(error){root.innerHTML=`<div class="card upload-warning">${esc(error.message)}</div>`;}}
window.addEventListener('keiyaku-auth-ready',load);
