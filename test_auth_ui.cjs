const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes={login:{hidden:true},protected:{hidden:true},'auth-user':{textContent:''},logout:{hidden:true,addEventListener:(n,f)=>nodes.logout[n]=f},'auth-error':{textContent:''},'google-login':{addEventListener:(n,f)=>nodes['google-login'][n]=f}};
const data=new Map();
let assigned='',fetches=[];
const context={
  document:{querySelector:s=>nodes[s.slice(1)]},
  location:{hash:'',origin:'https://keiyaku-max.netlify.app',pathname:'/',search:'',assign:u=>assigned=u},
  history:{replaceState:()=>{}},URLSearchParams,
  sessionStorage:{getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k)},
  fetch:async(url,options={})=>{fetches.push({url,options});return {ok:true,json:async()=>({email:'tester@example.com'})}}
};
vm.createContext(context);
vm.runInContext(fs.readFileSync('web/auth.js','utf8'),context);
setImmediate(async()=>{
  assert.equal(nodes.login.hidden,false); assert.equal(nodes.protected.hidden,true);
  nodes['google-login'].click();
  assert.match(assigned,/\/auth\/v1\/authorize\?provider=google/);
  assert.match(decodeURIComponent(assigned),/redirect_to=https:\/\/keiyaku-max\.netlify\.app\//);
  console.log('PASS: unauthenticated users are gated and Google OAuth uses the allow-listed return URL.');
});
