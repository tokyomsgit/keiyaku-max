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

function createForm(){newPdfs=[];root.innerHTML=`<nav class="steps"><a class="active">① 資料</a><a>② 要確認</a><a>③ 契約書生成</a></nav><p><button id="back">← 案件一覧へ</button></p><div class="card"><h1>新しい契約書を作成</h1><p>PDFは一度にまとめても、1件ずつ続けて追加しても構いません。</p><label class="pdf-drop" id="pdf-drop"><strong>PDFをここにドラッグ</strong><span>またはクリックして選択（複数可）</span><input id="pdf-files" type="file" accept="application/pdf,.pdf" multiple hidden></label><div id="file-list"></div><div class="actions"><button id="start-new" class="primary" disabled>選択した資料を読み取る</button></div><p id="status" role="status"></p><details id="manual"><summary>PDFから判定できない場合のみ手入力</summary><div class="facts new-case-form"><label>物件名<input id="building-name"></label><label>号室<input id="unit-name"></label><label>登記上の所在<input id="registry-location"></label><label>家屋番号<input id="house-number"></label><label>住居表示（任意）<input id="display-address"></label></div><div class="actions"><button id="save-new">手入力で作成</button></div></details></div>`;document.querySelector('#back').onclick=list;const input=document.querySelector('#pdf-files'),drop=document.querySelector('#pdf-drop');input.onchange=()=>{selectPdfs(input.files);input.value='';};drop.ondragover=e=>{e.preventDefault();drop.classList.add('is-dragging')};drop.ondragleave=()=>drop.classList.remove('is-dragging');drop.ondrop=e=>{e.preventDefault();drop.classList.remove('is-dragging');selectPdfs(e.dataTransfer.files)};document.querySelector('#file-list').onclick=e=>{const button=e.target.closest('[data-remove-pdf]');if(button)removePdf(Number(button.dataset.removePdf));};document.querySelector('#start-new').onclick=importPdfs;document.querySelector('#save-new').onclick=createNew;}

let newPdfs=[];
function pdfKey(file){return `${file.name}\n${file.size}\n${file.lastModified}`;}
function renderPdfList(){document.querySelector('#file-list').innerHTML=newPdfs.length?`<p><strong>読取する資料（${newPdfs.length}件）</strong></p>${newPdfs.map((file,index)=>`<p>✓ ${esc(file.name)} <span class="muted">${(file.size/1024/1024).toFixed(1)}MB</span> <button type="button" data-remove-pdf="${index}" aria-label="${esc(file.name)}を削除">削除</button></p>`).join('')}`:'';document.querySelector('#start-new').disabled=!newPdfs.length;}
function selectPdfs(files){const existing=new Set(newPdfs.map(pdfKey));for(const file of Array.from(files)){if(!(file.type==='application/pdf'||file.name.toLowerCase().endsWith('.pdf')))continue;const key=pdfKey(file);if(!existing.has(key)&&newPdfs.length<10){newPdfs.push(file);existing.add(key);}}renderPdfList();}
function removePdf(index){newPdfs.splice(index,1);renderPdfList();}
async function sha256(file){const digest=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());return Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');}
async function importPdfs(){const button=document.querySelector('#start-new'),status=document.querySelector('#status');button.disabled=true;button.textContent='資料を確認中…';status.textContent='解析済みデータを確認しています。';try{const files=[];for(const file of newPdfs)files.push({name:file.name,hash:await sha256(file)});const result=await (await request('import-cached',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({files})})).json();if(!result.cached){status.textContent=`初回解析が必要な資料です：${result.missing.join('、')}。下の手入力を開くか、管理者の解析完了後に再度追加してください。`;document.querySelector('#manual').open=true;button.disabled=false;return;}liveState=result.state;detail(result.case_id);}catch(error){status.textContent=error.message;button.disabled=false;}finally{button.textContent='資料を読み取って始める';}}

async function createNew(){const button=document.querySelector('#save-new'),status=document.querySelector('#status');button.disabled=true;status.textContent='登録しています…';try{const body={building_name:document.querySelector('#building-name').value,unit_name:document.querySelector('#unit-name').value,registry_location:document.querySelector('#registry-location').value,house_number:document.querySelector('#house-number').value,display_address:document.querySelector('#display-address').value};const result=await (await request('create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();liveState=result.state;detail(result.case_id);}catch(error){status.textContent=error.message;button.disabled=false;}}

function detail(id){
  const item=liveState.cases.find(c=>c.id===id);if(!item)return list();
  const missing=item.fields.filter(f=>f.value===null||f.value===undefined||f.value==='').length;
  root.innerHTML=`<nav class="steps"><a>① 資料</a><a class="${item.unresolved?'active':''}">② 要確認</a><a class="${item.unresolved?'':'active'}">③ 契約書生成</a></nav><p><button id="back">← 物件一覧へ</button> <button id="add-pdfs">PDFを追加</button></p>${item.reviews?.map(review=>`<div class="card"><div class="review-heading"><div><h2>${esc(review.label)}</h2><p>新旧どちらを使うか選んでください。</p></div><span class="review-remaining">要確認</span></div><div class="review-choices"><button data-decision="old" data-diff="${esc(review.diff_id)}"><span>現在の値を使う</span><strong>${esc(display(review.old_value))}</strong></button><button class="primary" data-decision="new" data-diff="${esc(review.diff_id)}"><span>新しい資料を使う</span><strong>${esc(display(review.new_value))}</strong></button></div></div>`).join('')||''}<div class="card"><div class="review-heading"><div><h2>${esc(item.building_name)} ${esc(item.unit_name)}</h2><p>Excelへ反映する主要情報</p></div>${item.unresolved?`<span class="review-remaining">あと${item.unresolved}件確認</span>`:'<span class="review-complete">✓ 差分確認済み</span>'}</div><dl class="facts">${item.fields.map(f=>`<div><dt>${esc(f.label)}</dt><dd>${esc(display(f.value))}</dd></div>`).join('')}</dl>${missing?`<p class="muted">未取得：${missing}項目。未取得欄は空欄のまま生成します。</p>`:''}${item.unresolved?'<p class="upload-warning">確認が必要な差分を解消すると生成できます。</p>':'<p class="success">契約書を生成できます。</p>'}<div class="actions"><button id="generate" class="primary" ${item.unresolved?'disabled':''}>契約書Excelを生成</button></div><p id="status" role="status"></p></div>`;
  document.querySelector('#back').onclick=list;
  document.querySelector('#add-pdfs').onclick=createForm;
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
