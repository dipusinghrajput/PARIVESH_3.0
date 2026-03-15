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
let _chatOpen = false;
let _chatAppId = null;   // set by pages that know their app_id

function toggleChatbot() {
  const w = document.getElementById('chatbot-window');
  if (!w) return;
  _chatOpen = !_chatOpen;
  w.classList.toggle('open', _chatOpen);
  if (_chatOpen) {
    const inp = document.getElementById('chat-input');
    if (inp) inp.focus();
  }
}

/** Call this from any page that has an application context, e.g. case_file.html */
function setChatAppId(appId) { _chatAppId = appId; }

/** Convert simple markdown-like syntax to safe HTML for chat bubbles */
function _chatMarkdown(text) {
  return text
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')  // escape first
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/_(.+?)_/g, '<em>$1</em>')
    .replace(/\n/g, '<br>');
}

function _appendMsg(text, role) {
  const box = document.getElementById('chat-messages');
  if (!box) return;
  const div = document.createElement('div');
  div.className = `chat-msg ${role}`;
  div.innerHTML = _chatMarkdown(text);
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function _showTyping() {
  const box = document.getElementById('chat-messages');
  if (!box) return;
  const el = document.createElement('div');
  el.className = 'chat-msg bot chat-typing';
  el.id = '_chat_typing';
  el.innerHTML = '<span class="typing-dot"></span><span class="typing-dot"></span><span class="typing-dot"></span>';
  box.appendChild(el);
  box.scrollTop = box.scrollHeight;
}

function _hideTyping() {
  const el = document.getElementById('_chat_typing');
  if (el) el.remove();
}

function _appendQuickReplies(chips) {
  const box = document.getElementById('chat-messages');
  if (!box || !chips || !chips.length) return;
  const wrap = document.createElement('div');
  wrap.className = 'chat-chips';
  chips.forEach(chip => {
    const btn = document.createElement('button');
    btn.className = 'chat-chip';
    btn.textContent = chip;
    btn.onclick = () => { wrap.remove(); sendChatMsg(chip); };
    wrap.appendChild(btn);
  });
  box.appendChild(wrap);
  box.scrollTop = box.scrollHeight;
}

async function sendChatMsg(overrideMsg) {
  const inp = document.getElementById('chat-input');
  const msg = overrideMsg || (inp ? inp.value.trim() : '');
  if (!msg) return;
  if (inp) inp.value = '';

  // Remove any existing quick-reply chips
  document.querySelectorAll('.chat-chips').forEach(el => el.remove());

  _appendMsg(msg, 'user');
  _showTyping();

  try {
    const payload = { message: msg };
    if (_chatAppId) payload.app_id = _chatAppId;
    const res = await apiFetch('/chatbot', { method: 'POST', body: JSON.stringify(payload) });
    _hideTyping();
    _appendMsg(res.reply, 'bot');

    // Show quick-reply chips on greetings/fallback
    if (res.reply.includes('I can help') || res.reply.includes('PARIVESH Assistant')) {
      _appendQuickReplies([
        'Application status?',
        'What is EDS?',
        'Documents required?',
        'How long will it take?',
      ]);
    }
  } catch {
    _hideTyping();
    _appendMsg('Sorry, I couldn\'t process that. Please try again.', 'bot');
  }
}

function initChatbot() {
  const inp = document.getElementById('chat-input');
  if (inp) inp.addEventListener('keydown', e => { if (e.key === 'Enter') sendChatMsg(); });
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
