/* Google authentication backed by the existing Supabase Auth project. */
'use strict';
const AUTH_URL='https://afdtohxuzuwlqmjbrpar.supabase.co';
const AUTH_KEY='sb_publishable_4I1EXj6iMy3J-_nxBrOasw_1CRPXyw4';
const SESSION_KEY='keiyaku-max-auth';
const login=document.querySelector('#login');
const protectedArea=document.querySelector('#protected');
const authUser=document.querySelector('#auth-user');
const logout=document.querySelector('#logout');
const authError=document.querySelector('#auth-error');

function readCallback(){
  const p=new URLSearchParams(location.hash.replace(/^#/,''));
  const accessToken=p.get('access_token');
  if(accessToken){
    sessionStorage.setItem(SESSION_KEY,JSON.stringify({access_token:accessToken,refresh_token:p.get('refresh_token'),expires_at:Date.now()+Number(p.get('expires_in')||3600)*1000}));
    history.replaceState(null,'',location.pathname+location.search);
  }
  if(p.get('error_description')) authError.textContent=p.get('error_description');
}
function session(){try{return JSON.parse(sessionStorage.getItem(SESSION_KEY)||'null');}catch{return null;}}
function showLogin(message=''){
  sessionStorage.removeItem(SESSION_KEY); login.hidden=false; protectedArea.hidden=true; logout.hidden=true;
  authUser.textContent='実運用テスト'; authError.textContent=message;
}
function showApp(user){
  login.hidden=true; protectedArea.hidden=false; logout.hidden=false;
  authUser.textContent=user.email||'ログイン中';
}
async function verify(){
  const current=session();
  if(!current?.access_token){showLogin();return;}
  try{
    const res=await fetch(AUTH_URL+'/auth/v1/user',{headers:{apikey:AUTH_KEY,Authorization:'Bearer '+current.access_token}});
    if(!res.ok) throw new Error('session');
    showApp(await res.json());
  }catch{showLogin('ログインの有効期限が切れました。もう一度ログインしてください。');}
}
document.querySelector('#google-login').addEventListener('click',()=>{
  const redirect=location.origin+location.pathname;
  location.assign(AUTH_URL+'/auth/v1/authorize?provider=google&redirect_to='+encodeURIComponent(redirect));
});
logout.addEventListener('click',async()=>{
  const current=session();
  if(current?.access_token){try{await fetch(AUTH_URL+'/auth/v1/logout',{method:'POST',headers:{apikey:AUTH_KEY,Authorization:'Bearer '+current.access_token}});}catch{}}
  showLogin();
});
readCallback();
verify();
