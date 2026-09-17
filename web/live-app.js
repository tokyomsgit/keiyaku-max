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
  document.querySelector('#create').onclick=()=>createForm();
  root.querySelectorAll('[data-open]').forEach(button=>button.onclick=()=>detail(button.dataset.open));
}

let targetCase=null;
function createForm(caseId=null){forgetJob();targetCase=caseId;newPdfs=[];root.innerHTML=`<nav class="steps"><a class="active">① 資料</a><a>② 要確認</a><a>③ 契約書生成</a></nav><p><button id="back">← 案件一覧へ</button></p><div class="card"><h1>${caseId?'資料を追加':'新しい契約書を作成'}</h1><p>PDFは一度にまとめても、1件ずつ続けて追加しても構いません。初めての資料も自動で読み取ります。</p><label class="pdf-drop" id="pdf-drop"><strong>PDFをここにドラッグ</strong><span>またはクリックして選択（複数可）</span><input id="pdf-files" type="file" accept="application/pdf,.pdf" multiple hidden></label><div id="file-list"></div><div class="actions"><button id="start-new" class="primary" disabled>選択した資料を読み取る</button></div><p id="status" role="status"></p><details id="manual"><summary>PDFから判定できない場合のみ手入力</summary><div class="facts new-case-form"><label>物件名<input id="building-name"></label><label>号室<input id="unit-name"></label><label>登記上の所在<input id="registry-location"></label><label>家屋番号<input id="house-number"></label><label>住居表示（任意）<input id="display-address"></label></div><div class="actions"><button id="save-new">手入力で作成</button></div></details></div>`;document.querySelector('#back').onclick=list;const input=document.querySelector('#pdf-files'),drop=document.querySelector('#pdf-drop');input.onchange=()=>{selectPdfs(input.files);input.value='';};drop.ondragover=e=>{e.preventDefault();drop.classList.add('is-dragging')};drop.ondragleave=()=>drop.classList.remove('is-dragging');drop.ondrop=e=>{e.preventDefault();drop.classList.remove('is-dragging');selectPdfs(e.dataTransfer.files)};document.querySelector('#file-list').onclick=e=>{const button=e.target.closest('[data-remove-pdf]');if(button)removePdf(Number(button.dataset.removePdf));};document.querySelector('#start-new').onclick=importPdfs;document.querySelector('#save-new').onclick=createNew;}

let newPdfs=[];
function pdfKey(file){return `${file.name}\n${file.size}\n${file.lastModified}`;}
function renderPdfList(){document.querySelector('#file-list').innerHTML=newPdfs.length?`<p><strong>読取する資料（${newPdfs.length}件）</strong></p>${newPdfs.map((file,index)=>`<p>✓ ${esc(file.name)} <span class="muted">${(file.size/1024/1024).toFixed(1)}MB</span> <button type="button" data-remove-pdf="${index}" aria-label="${esc(file.name)}を削除">削除</button></p>`).join('')}`:'';document.querySelector('#start-new').disabled=!newPdfs.length;}
function selectPdfs(files){const existing=new Set(newPdfs.map(pdfKey));for(const file of Array.from(files)){if(!(file.type==='application/pdf'||file.name.toLowerCase().endsWith('.pdf')))continue;const key=pdfKey(file);if(!existing.has(key)&&newPdfs.length<10){newPdfs.push(file);existing.add(key);}}renderPdfList();}
function removePdf(index){newPdfs.splice(index,1);renderPdfList();}
async function sha256(file){const digest=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());return Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');}
const INGEST='/.netlify/functions/ingest';
const KIND_LABELS={purchase:'購入時重要事項説明書',registry:'登記簿謄本（建物・土地）',report:'重要事項調査報告書',rules:'管理規約・使用細則',zoning:'用途地域資料',skip:'この資料は読み取らない'};
let activeJob=null,pollTimer=null;
async function ingest(action,body){const token=window.KeiyakuAuth?.token();if(!token)throw Error('ログインし直してください。');const url=`${INGEST}?action=${action}`+(body?'':`&job_id=${encodeURIComponent(activeJob)}`);const response=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},body:JSON.stringify(body)}:{headers:{Authorization:`Bearer ${token}`}});let data={};try{data=await response.json();}catch{}if(!response.ok)throw Error(data.error||'処理に失敗しました。');return data;}
async function openCase(caseId,note=''){liveState=await (await request('state')).json();if(liveState.cases.some(c=>c.id===caseId))detail(caseId);else list();const status=document.querySelector('#status');if(note&&status)status.textContent=note;}
async function importPdfs(){const button=document.querySelector('#start-new'),status=document.querySelector('#status');button.disabled=true;button.textContent='資料を確認中…';status.textContent='解析済みの資料か確認しています。';try{const files=[],byHash=new Map();for(const file of newPdfs){const hash=await sha256(file);byHash.set(hash,file);files.push({name:file.name,size:file.size,hash});}const started=await ingest('start',{files,case_id:targetCase});if(started.cached){await openCase(started.case_id,'解析済みの資料から案件を開きました。');return;}const sending=started.uploads.filter(u=>!u.skip);for(const [index,upload] of sending.entries()){status.textContent=`PDFを非公開の保存先へ送信しています（${index+1}/${sending.length}）`;const form=new FormData();form.append('cacheControl','3600');form.append('',byHash.get(upload.hash));const response=await fetch(upload.url,{method:'PUT',headers:{'x-upsert':'false'},body:form});if(!response.ok&&response.status!==409&&response.status!==400)throw Error('PDFを送信できませんでした。通信環境を確認して再度お試しください。');}activeJob=started.job_id;try{sessionStorage.setItem('keiyaku-max-job',activeJob);}catch{}showJob(await ingest('run',{job_id:activeJob}));}catch(error){status.textContent=error.message;button.disabled=false;button.textContent='選択した資料を読み取る';}}
function showJob(job){clearTimeout(pollTimer);activeJob=job.job_id;const busy=['queued','running','awaiting_upload'].includes(job.status);let body='';
if(busy)body=`<p class="job-progress" role="status">${esc(job.message||'読み取り中です。')}</p><p class="muted">資料の枚数により1〜5分ほどかかります。この画面を開いたままお待ちください。</p>`;
else if(job.status==='needs_kind')body=`<p class="upload-warning">${esc(job.message)}</p>${(job.unknown||[]).map(f=>`<label class="kind-row"><span>${esc(f.name)}</span><select data-kind="${esc(f.hash)}"><option value="">種類を選択</option>${Object.entries(KIND_LABELS).map(([k,v])=>`<option value="${k}">${v}</option>`).join('')}</select></label>`).join('')}<div class="actions"><button id="job-kinds" class="primary">種類を確定して読み取る</button><button id="job-cancel">PDFを選び直す</button></div>`;
else if(job.status==='needs_consent')body=`<p class="upload-warning">${esc(job.message)}</p><p>AI料金の概算：<strong>${job.estimate_jpy===null||job.estimate_jpy===undefined?'事前に計算できません':'約'+Number(job.estimate_jpy).toLocaleString('ja-JP')+'円'}</strong></p><div class="actions"><button id="job-consent" class="primary">AIで読み取る</button><button id="job-cancel">読み取らずに戻る</button></div>`;
else if(job.status==='needs_candidate')body=`<p class="upload-warning">${esc(job.message)} 登記上の所在と家屋番号を確認して、対象の物件を選んでください。</p><fieldset class="candidate-list"><legend>物件候補</legend>${(job.candidates||[]).map(c=>`<label><input type="radio" name="candidate" value="${esc(c.id)}"><span><strong>${esc(c.building_name||'物件名未取得')} ${esc(c.unit_name||'')}</strong><small>家屋番号：${esc(display(c.house_number))}　所在：${esc(display(c.registry_location))}</small></span></label>`).join('')}</fieldset><div class="actions"><button id="job-candidate" class="primary">選択した物件で確定</button><button id="job-cancel">確定せずに戻る</button></div>`;
else if(job.status==='needs_purchase_verification')body=purchaseVerificationBody(job);
else if(job.status==='done')body=`<p class="success">✓ ${esc(job.message)}</p>`;
else body=`<p class="upload-warning">${esc(job.message||'読み取りを完了できませんでした。')}</p><div class="actions"><button id="job-retry" class="primary">もう一度読み取る</button><button id="job-cancel">PDFを選び直す</button></div>`;
root.innerHTML=`<nav class="steps"><a class="active">① 資料</a><a>② 要確認</a><a>③ 契約書生成</a></nav><div class="card"><h1>資料の読み取り</h1><ul class="job-files">${(job.files||[]).map(f=>`<li>${esc(f.name)}</li>`).join('')}</ul>${body}<p id="status" role="status"></p></div>`;
const say=text=>{document.querySelector('#status').textContent=text;};
const act=async(payload,button)=>{button.disabled=true;try{showJob(await ingest('run',{job_id:job.job_id,...payload}));}catch(error){say(error.message);button.disabled=false;}};
const on=(id,handler)=>{const button=document.querySelector('#'+id);if(button)button.onclick=()=>handler(button);};
on('job-cancel',()=>{forgetJob();createForm(targetCase);});
on('job-retry',button=>act({},button));
on('job-consent',button=>act({ai_confirmed:true},button));
on('job-kinds',button=>{const kinds={};for(const select of root.querySelectorAll('[data-kind]')){if(!select.value)return say('すべてのPDFの種類を選んでください。');kinds[select.dataset.kind]=select.value;}act({kinds},button);});
on('job-candidate',button=>{const chosen=root.querySelector('input[name="candidate"]:checked');if(!chosen)return say('物件を1件選んでください。');act({candidate_id:chosen.value},button);});
on('purchase-check-all',()=>{root.querySelectorAll('[data-verify]').forEach(box=>box.checked=true);});
on('job-purchase-confirm',button=>{
  const propertyType=document.querySelector('#purchase-property-type').value;
  if(!propertyType)return say('物件種別を選んでください。');
  const entries=[];
  for(const row of root.querySelectorAll('.purchase-field')){
    const code=row.dataset.field;
    if(!row.querySelector('[data-verify]').checked)continue;
    const valueInput=row.querySelector('[data-value]');
    let value=valueInput.value;
    if(row.dataset.kind==='number'){value=Number(value);if(!Number.isFinite(value))return say(`「${row.dataset.label}」は数値を入力してください。`);}
    else if(row.dataset.kind==='boolean'){value=value==='true';}
    else if(row.dataset.kind==='json'){try{value=JSON.parse(value);}catch{return say(`「${row.dataset.label}」の形式を確認してください。`);}}
    const page=Number(row.querySelector('[data-page]').value);
    const quote=row.querySelector('[data-quote]').value.trim();
    if(!Number.isInteger(page)||page<1)return say(`「${row.dataset.label}」のページ番号を入力してください。`);
    if(!quote)return say(`「${row.dataset.label}」の原文を入力してください。`);
    entries.push({code,value,page_no:page,source_text:quote});
  }
  if(!entries.length)return say('原本で確認できた項目にチェックを入れてください。');
  act({property_type:propertyType,purchase_entries:entries},button);
});
if(job.status==='done'){forgetJob();openCase(job.case_id,(job.warnings||[]).join(' ')).catch(error=>say(error.message));}
if(busy)pollTimer=setTimeout(pollJob,8000);}

function purchaseVerificationBody(job){
  const rows=(job.fields||[]).map(f=>{
    const val=f.kind==='json'?JSON.stringify(f.value):f.kind==='boolean'?String(f.value):f.value;
    const input=f.kind==='boolean'
      ?`<select data-value><option value="true" ${f.value?'selected':''}>有・該当</option><option value="false" ${f.value?'':'selected'}>無・非該当</option></select>`
      :f.kind==='json'
        ?`<textarea data-value rows="2">${esc(val)}</textarea>`
        :f.kind==='number'
          ?`<input type="number" step="any" data-value value="${esc(val)}">`
          :`<input type="text" data-value value="${esc(val)}">`;
    return `<div class="purchase-field" data-field="${esc(f.code)}" data-kind="${f.kind}" data-label="${esc(f.label)}">
      <label class="purchase-field-check"><input type="checkbox" data-verify><strong>${esc(f.label)}</strong></label>
      ${input}
      <div class="purchase-field-evidence"><label>ページ<input type="number" min="1" max="${job.page_count||99}" data-page value="${f.page_no||1}"></label>
      <label>原文<input type="text" data-quote value="${esc(f.source_text||'')}"></label></div>
    </div>`;
  }).join('');
  return `<p class="upload-warning">${esc(job.message)}</p><p class="muted">原本（PDF）と見比べて、AIの読み取り結果が正しいか確認してください。違う場合は値を修正してからチェックを入れてください。未確認のままにした項目は保留になります。</p>
    <label class="purchase-property-type">物件種別<select id="purchase-property-type"><option value="">選択してください</option>${(job.property_type_options||[]).map(o=>`<option value="${esc(o.value)}">${esc(o.label)}</option>`).join('')}</select></label>
    <p><button type="button" id="purchase-check-all">すべて確認済みにする</button></p>
    <div class="purchase-fields">${rows}</div>
    <div class="actions"><button id="job-purchase-confirm" class="primary">確認した内容で取り込む</button><button id="job-cancel">PDFを選び直す</button></div>`;
}
async function pollJob(){if(!activeJob)return;try{showJob(await ingest('status'));}catch(error){const status=document.querySelector('#status');if(status)status.textContent=error.message+' 自動で再確認します。';pollTimer=setTimeout(pollJob,15000);}}
function forgetJob(){clearTimeout(pollTimer);activeJob=null;try{sessionStorage.removeItem('keiyaku-max-job');}catch{}}

async function createNew(){const button=document.querySelector('#save-new'),status=document.querySelector('#status');button.disabled=true;status.textContent='登録しています…';try{const body={building_name:document.querySelector('#building-name').value,unit_name:document.querySelector('#unit-name').value,registry_location:document.querySelector('#registry-location').value,house_number:document.querySelector('#house-number').value,display_address:document.querySelector('#display-address').value};const result=await (await request('create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();liveState=result.state;detail(result.case_id);}catch(error){status.textContent=error.message;button.disabled=false;}}

const dateOnly=v=>v?String(v).slice(0,10):'基準日未設定';
function displayReview(value){
  if(value===null||value===undefined||value==='')return '未取得';
  if(typeof value==='boolean')return value?'有':'無';
  if(Array.isArray(value)){
    if(!value.length)return '（該当なし）';
    return value.map(displayReview).join('／');
  }
  if(typeof value==='object')return Object.values(value).filter(v=>v!==null&&v!==undefined&&v!=='').map(displayReview).join(' ');
  return display(value);
}
function candidateCard(group,candidate,isBaseline){
  const id=`review-${esc(group.field_code)}`;
  const radioValue=isBaseline?'baseline':esc(candidate.diff_id);
  const recommended=!isBaseline&&group.recommended_diff_id===candidate.diff_id;
  const checked=recommended||(isBaseline&&!group.recommended_diff_id);
  const evidence=candidate.source_text?`<details><summary>原文を見る</summary><p>${esc(candidate.source_text)}</p></details>`:'';
  const source=isBaseline?(candidate.filename?`現在の値（${esc(candidate.filename)}）`:'現在の値'):esc(candidate.filename||'資料名不明');
  return `<label class="review-option"><input type="radio" name="${id}" value="${radioValue}" ${checked?'checked':''}>
    <span class="review-option-body"><strong>${esc(displayReview(candidate.value))}</strong>${recommended?'<span class="pill">推奨</span>':''}
    <small>${source}　基準日：${esc(dateOnly(candidate.as_of_date))}${candidate.page_no?`　${candidate.page_no}ページ`:''}</small>
    ${evidence}</span></label>`;
}
function zoningCard(zoning){
  if(!zoning)return '';
  const multi=zoning.zones.length>1;
  const zoneBlock=(zone,index)=>{
    const label=zone.zone_label||(multi?String.fromCharCode(65+index):null);
    const moves=multi?`<span class="zoning-move">${index>0?`<button type="button" class="zoning-move-up" data-index="${index}" title="上へ">▲</button>`:''}${index<zoning.zones.length-1?`<button type="button" class="zoning-move-down" data-index="${index}" title="下へ">▼</button>`:''}</span>`:'';
    const head=label||moves?`<div class="zoning-zone-head">${label?`<h3>${esc(label)}</h3>`:''}${zone.source_filename?`<span class="muted">${esc(zone.source_filename)}</span>`:''}${moves}</div>`:'';
    return `<div class="zoning-zone">${head}<dl class="facts">${zone.fields.map(f=>`<div><dt>${esc(f.label)}${f.needs_review?' <span class="pill warn">要確認</span>':''}</dt><dd>${esc(display(f.value))}</dd></div>`).join('')}</dl></div>`;
  };
  return `<div class="card"><div class="review-heading"><div><h2>用途地域・都市計画</h2><p>${esc(zoning.filename)}${zoning.as_of_date?`　基準日：${esc(zoning.as_of_date)}`:''}</p></div>${zoning.reviewed?'<span class="review-complete">✓ 確認済み</span>':'<span class="review-remaining">要確認</span>'}</div>${multi?'<p class="muted">契約書の(A)(B)はこの並び順で決まります。境界のどちら側か確認し、違う場合は▲▼で入れ替えてください。</p>':''}${zoning.zones.map(zoneBlock).join('')}${zoning.reviewed?'':'<p class="upload-warning">境界・指定内容を原本と照合してください。</p>'}<p id="zoning-status" role="status"></p></div>`;
}
function reviewCard(group){
  return `<div class="card review-group" data-field="${esc(group.field_code)}"><div class="review-heading"><div><h2>${esc(group.label)}</h2><p>使用する値を選んでください。</p></div><span class="review-remaining">要確認</span></div>
    <div class="review-options">${candidateCard(group,group.baseline,true)}${group.candidates.map(c=>candidateCard(group,c,false)).join('')}</div></div>`;
}
async function detail(id){
  const item=liveState.cases.find(c=>c.id===id);if(!item)return list();
  const missing=item.fields.filter(f=>f.value===null||f.value===undefined||f.value==='').length;
  let groups=[],zoning=null;
  try{groups=(await reviewApi('list','GET',null,`&case_id=${encodeURIComponent(id)}`)).groups||[];}catch{}
  try{
    const token=window.KeiyakuAuth?.token();
    if(token){const r=await fetch(`/.netlify/functions/zoning?action=get&case_id=${encodeURIComponent(id)}`,{headers:{Authorization:`Bearer ${token}`}});if(r.ok)zoning=(await r.json()).zoning;}
  }catch{}
  root.innerHTML=`<nav class="steps"><a>① 資料</a><a class="${groups.length?'active':''}">② 要確認</a><a class="${groups.length?'':'active'}">③ 契約書生成</a></nav><p><button id="back">← 物件一覧へ</button> <button id="add-pdfs">PDFを追加</button></p>${groups.map(reviewCard).join('')}${groups.length?'<div class="card"><div class="actions"><button id="confirm-reviews" class="primary">選択した内容を確定</button></div><p id="review-status" role="status"></p></div>':''}${zoningCard(zoning)}<div class="card"><div class="review-heading"><div><h2>${esc(item.building_name)} ${esc(item.unit_name)}</h2><p>Excelへ反映する主要情報</p></div>${groups.length?`<span class="review-remaining">あと${groups.length}件確認</span>`:'<span class="review-complete">✓ 差分確認済み</span>'}</div><dl class="facts">${item.fields.map(f=>`<div><dt>${esc(f.label)}</dt><dd>${esc(display(f.value))}</dd></div>`).join('')}</dl>${missing?`<p class="muted">未取得：${missing}項目。未取得欄は空欄のまま生成します。</p>`:''}${groups.length?'<p class="upload-warning">確認が必要な項目を解消すると生成できます。</p>':'<p class="success">契約書を生成できます。</p>'}<div class="actions"><button id="generate" class="primary" ${groups.length?'disabled':''}>契約書Excelを生成</button></div><p id="status" role="status"></p></div>`;
  document.querySelector('#back').onclick=list;
  document.querySelector('#add-pdfs').onclick=()=>createForm(item.id);
  document.querySelector('#generate').onclick=()=>generate(item);
  const confirmButton=document.querySelector('#confirm-reviews');
  if(confirmButton)confirmButton.onclick=()=>confirmReviews(item,groups);
  if(zoning){
    const moveZone=async(index,dir)=>{
      const status=document.querySelector('#zoning-status');
      const order=zoning.zones.map((_,i)=>i);
      [order[index],order[index+dir]]=[order[index+dir],order[index]];
      if(status)status.textContent='並び替えています…';
      try{
        const token=window.KeiyakuAuth?.token();if(!token)throw Error('ログインし直してください。');
        const response=await fetch('/.netlify/functions/zoning?action=reorder',{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},body:JSON.stringify({case_id:item.id,order})});
        const result=await response.json();if(!response.ok)throw Error(result.error||'並び替えに失敗しました。');
        detail(item.id);
      }catch(error){if(status)status.textContent=error.message;}
    };
    root.querySelectorAll('.zoning-move-up').forEach(btn=>btn.onclick=()=>moveZone(Number(btn.dataset.index),-1));
    root.querySelectorAll('.zoning-move-down').forEach(btn=>btn.onclick=()=>moveZone(Number(btn.dataset.index),1));
  }
}

async function reviewApi(action,method,body,extraQuery=''){
  const token=window.KeiyakuAuth?.token();if(!token)throw Error('ログインし直してください。');
  const response=await fetch(`/.netlify/functions/review?action=${action}${extraQuery}`,{method,headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},body:body?JSON.stringify(body):undefined});
  const result=await response.json();if(!response.ok)throw Error(result.error||'処理に失敗しました。');
  return result;
}

async function confirmReviews(item,groups){
  const button=document.querySelector('#confirm-reviews'),status=document.querySelector('#review-status');
  button.disabled=true;status.textContent='確定しています…';
  const selections=groups.map(group=>{
    const chosen=document.querySelector(`input[name="review-${CSS.escape(group.field_code)}"]:checked`)?.value;
    return {field_code:group.field_code,diff_id:chosen&&chosen!=='baseline'?chosen:null};
  });
  try{
    await reviewApi('confirm','POST',{case_id:item.id,selections});
    detail(item.id);
  }catch(error){status.textContent=error.message;button.disabled=false;}
}

async function generate(item){
  const button=document.querySelector('#generate'),status=document.querySelector('#status');button.disabled=true;button.textContent='契約書作成中…';status.textContent='本番ひな形へ反映しています。';
  try{
    const token=window.KeiyakuAuth?.token();if(!token)throw Error('ログインし直してください。');const response=await fetch('/.netlify/functions/generate',{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},body:JSON.stringify({case_id:item.id})});if(!response.ok){let data={};try{data=await response.json();}catch{}throw Error(data.error||'契約書を生成できませんでした。');}
    const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement('a');
    link.href=url;link.download=`契約書_${item.building_name}_${item.unit_name}.xlsm`;link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);
    status.textContent='✓ 契約書を作成しました。「要確認」と入った欄は原本で確認してください。もう一度押すと再ダウンロードできます。';button.disabled=false;
  }catch(error){status.textContent=error.message;button.disabled=false;}finally{button.textContent='契約書Excelを生成';}
}

async function load(){root.innerHTML='<div class="card"><p>物件データを読み込んでいます…</p></div>';try{let saved=null;try{saved=sessionStorage.getItem('keiyaku-max-job');}catch{}if(saved){activeJob=saved;try{showJob(await ingest('status'));return;}catch{forgetJob();}}liveState=await (await request('state')).json();list();}catch(error){root.innerHTML=`<div class="card upload-warning">${esc(error.message)}</div>`;}}
window.addEventListener('keiyaku-auth-ready',load);

if(!document.querySelector('#protected').hidden)load();
