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
  root.innerHTML=`<nav class="steps" aria-label="契約書作成の工程"><a>① 資料</a><a>② 要確認</a><a class="active" aria-current="step">③ 契約書生成</a></nav><div class="top"><div><h1>契約書を生成</h1><p>Supabaseに保存済みの物件データを、本番Excelひな形へ反映します。</p></div><button id="refresh">最新情報に更新</button></div>${cases.length?`<div class="card table-scroll"><table><thead><tr><th>物件名</th><th>号室</th><th>所在地</th><th>要確認</th><th>操作</th></tr></thead><tbody>${cases.map(c=>`<tr class="case-row"><td><strong>${esc(c.building_name)}</strong></td><td>${esc(c.unit_name)}</td><td>${esc(c.address)}</td><td>${c.unresolved?`<span class="pill warn">${c.unresolved}件</span>`:'<span class="pill">確認済み</span>'}</td><td><button class="primary" data-open="${esc(c.id)}">内容を確認して生成</button></td></tr>`).join('')}</tbody></table></div>`:'<div class="card empty"><p>生成できる物件データがありません。</p><p>先に資料を登録してください。</p></div>'}`;
  document.querySelector('#refresh').onclick=load;
  root.querySelectorAll('[data-open]').forEach(button=>button.onclick=()=>detail(button.dataset.open));
}

function detail(id){
  const item=liveState.cases.find(c=>c.id===id);if(!item)return list();
  const missing=item.fields.filter(f=>f.value===null||f.value===undefined||f.value==='').length;
  root.innerHTML=`<nav class="steps"><a>① 資料</a><a>② 要確認</a><a class="active">③ 契約書生成</a></nav><p><button id="back">← 物件一覧へ</button></p><div class="card"><div class="review-heading"><div><h2>${esc(item.building_name)} ${esc(item.unit_name)}</h2><p>Excelへ反映する主要情報</p></div>${item.unresolved?`<span class="review-remaining">あと${item.unresolved}件確認</span>`:'<span class="review-complete">✓ 差分確認済み</span>'}</div><dl class="facts">${item.fields.map(f=>`<div><dt>${esc(f.label)}</dt><dd>${esc(display(f.value))}</dd></div>`).join('')}</dl>${missing?`<p class="muted">未取得：${missing}項目。未取得欄は空欄のまま生成します。</p>`:''}${item.unresolved?'<p class="upload-warning">確認が必要な差分を解消すると生成できます。</p>':'<p class="success">契約書を生成できます。</p>'}<div class="actions"><button id="generate" class="primary" ${item.unresolved?'disabled':''}>契約書Excelを生成</button></div><p id="status" role="status"></p></div>`;
  document.querySelector('#back').onclick=list;
  document.querySelector('#generate').onclick=()=>generate(item);
}

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
