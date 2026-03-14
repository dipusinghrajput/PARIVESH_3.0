const API = '/api';

async function apiFetch(path, options={}) {
  const res = await fetch(API+path, {credentials:'include', headers:{'Content-Type':'application/json',...(options.headers||{})}, ...options});
  const data = await res.json().catch(()=>({}));
  if(!res.ok) throw new Error(data.error||`HTTP ${res.status}`);
  return data;
}
async function apiForm(path, formData, method='POST') {
  const res = await fetch(API+path, {method, credentials:'include', body:formData});
  const data = await res.json().catch(()=>({}));
  if(!res.ok) throw new Error(data.error||`HTTP ${res.status}`);
  return data;
}

async function requireAuth(allowedRoles=null) {
  try {
    const user = await apiFetch('/me');
    if(allowedRoles && !allowedRoles.includes(user.role)) {
      showToast('Access denied for your role.','error');
      setTimeout(()=>location.href='/dashboard',1500);
      return null;
    }
    return user;
  } catch { location.href='/login'; return null; }
}

function showToast(msg, type='info') {
  const icons={error:'⚠️',success:'✅',info:'ℹ️',warning:'⚠️',ai:'🤖'};
  const colors={error:'#FFEBEE',success:'#E8F5E9',info:'#E3F2FD',warning:'#FFF3E0',ai:'#F5F3FF'};
  const textColors={error:var_css('--red'),success:var_css('--green'),info:var_css('--primary-light'),warning:var_css('--orange'),ai:var_css('--ai-color')};
  const el=document.createElement('div');
  el.style.cssText=`position:fixed;top:66px;right:16px;z-index:9999;max-width:380px;padding:11px 15px;border-radius:8px;background:${colors[type]||colors.info};color:${textColors[type]||textColors.info};font-size:13px;font-weight:500;box-shadow:0 4px 16px rgba(0,0,0,0.12);display:flex;gap:8px;align-items:flex-start;animation:slideIn .3s ease;font-family:Inter,sans-serif;border:1px solid rgba(0,0,0,0.08);`;
  el.innerHTML=`<span>${icons[type]||''}</span><span>${msg}</span>`;
  document.body.appendChild(el);
  setTimeout(()=>el.remove(),4500);
}
function var_css(name){return getComputedStyle(document.documentElement).getPropertyValue(name).trim();}

function statusBadge(status) {
  const map={Draft:'draft',Submitted:'submitted',AIScreening:'aiscreening',Scrutiny:'scrutiny',EDS:'eds',Resubmitted:'resubmitted',Referred:'referred',MoMGenerated:'momgenerated',Finalized:'finalized'};
  const icons={Draft:'⬜',Submitted:'🔵',AIScreening:'🤖',Scrutiny:'🟠',EDS:'🔴',Resubmitted:'🟣',Referred:'🟢',MoMGenerated:'🩵',Finalized:'✅'};
  return `<span class="badge badge-${map[status]||'draft'}">${icons[status]||'●'} ${status}</span>`;
}

function fmtDate(iso){
  if(!iso)return'–';
  return new Date(iso).toLocaleString('en-IN',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'});
}
function fmtDateShort(iso){
  if(!iso)return'–';
  return new Date(iso).toLocaleDateString('en-IN',{day:'2-digit',month:'short',year:'numeric'});
}

async function renderTopbar(user) {
  const initials=user.name.split(' ').map(w=>w[0]).join('').slice(0,2).toUpperCase();
  const el=id=>document.getElementById(id);
  if(el('user-name')) el('user-name').textContent=user.name;
  if(el('user-role')) el('user-role').textContent=user.role;
  if(el('user-avatar')) el('user-avatar').textContent=initials;
  loadNotifications();
}

async function loadNotifications() {
  try {
    const notifs = await apiFetch('/notifications');
    const unread = notifs.filter(n=>!n.is_read).length;
    const badge = document.getElementById('notif-badge');
    if(badge){badge.textContent=unread;badge.style.display=unread?'block':'none';}
    const list = document.getElementById('notif-list');
    if(!list)return;
    if(!notifs.length){
      list.innerHTML='<div class="empty-state" style="padding:20px"><div class="empty-state-icon">🔔</div><div class="empty-state-text">No notifications</div></div>';
      return;
    }
    list.innerHTML=notifs.map(n=>`
      <div class="notif-item ${n.is_read?'':'unread'}" onclick="location.href='/case_file?id=${n.application_id}'">
        <div class="notif-item-title">${n.title}</div>
        <div class="notif-item-msg">${n.message}</div>
        <div class="notif-item-time">${fmtDate(n.created_at)}</div>
      </div>`).join('');
  } catch{}
}

function toggleNotifPanel() {
  const panel=document.getElementById('notif-panel');
  panel.classList.toggle('open');
  if(panel.classList.contains('open')){
    apiFetch('/notifications/read',{method:'POST'}).then(()=>{
      const b=document.getElementById('notif-badge');
      if(b)b.style.display='none';
    });
  }
}

async function logout() {
  await apiFetch('/logout',{method:'POST'}).catch(()=>{});
  location.href='/login';
}

document.addEventListener('click',e=>{
  const panel=document.getElementById('notif-panel');
  const btn=document.querySelector('.notif-btn');
  if(panel&&!panel.contains(e.target)&&btn&&!btn.contains(e.target))
    panel.classList.remove('open');
  const cw=document.getElementById('chatbot-window');
  const fab=document.getElementById('chatbot-fab');
  if(cw&&fab&&!cw.contains(e.target)&&!fab.contains(e.target))
    cw.classList.remove('open');
});

// ── CHATBOT ──────────────────────────────────────────────────────────────────
function toggleChatbot() {
  const w=document.getElementById('chatbot-window');
  if(w) w.classList.toggle('open');
}

async function sendChatMsg() {
  const inp=document.getElementById('chat-input');
  const msg=inp.value.trim();
  if(!msg)return;
  inp.value='';
  const box=document.getElementById('chat-messages');
  box.innerHTML+=`<div class="chat-msg user">${msg}</div>`;
  box.scrollTop=box.scrollHeight;
  try {
    const res=await apiFetch('/chatbot',{method:'POST',body:JSON.stringify({message:msg})});
    box.innerHTML+=`<div class="chat-msg bot">${res.reply}</div>`;
    box.scrollTop=box.scrollHeight;
  } catch {
    box.innerHTML+=`<div class="chat-msg bot">Sorry, I couldn't process that. Try again!</div>`;
  }
}

function initChatbot() {
  const w=document.getElementById('chat-input');
  if(w) w.addEventListener('keydown',e=>{if(e.key==='Enter')sendChatMsg();});
}

// ── GLOBAL SEARCH ─────────────────────────────────────────────────────────────
function initGlobalSearch() {
  const inp=document.getElementById('global-search');
  if(!inp)return;
  let t;
  inp.addEventListener('input',()=>{
    clearTimeout(t);
    t=setTimeout(async()=>{
      const q=inp.value.trim();
      if(!q)return;
      try {
        const res=await apiFetch(`/search?q=${encodeURIComponent(q)}`);
        if(res.length===1) location.href=`/case_file?id=${res[0].id}`;
        else if(res.length>1) location.href=`/dashboard?search=${encodeURIComponent(q)}`;
      }catch{}
    },500);
  });
}

// ── CSS ANIMATION INJECTION ───────────────────────────────────────────────────
const _s=document.createElement('style');
_s.textContent=`@keyframes slideIn{from{transform:translateX(20px);opacity:0}to{transform:none;opacity:1}}`;
document.head.appendChild(_s);
