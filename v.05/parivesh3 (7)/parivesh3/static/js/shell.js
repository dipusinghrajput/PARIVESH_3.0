function renderShell(activePage, userRole) {
  const all=[
    {href:'/dashboard',icon:'🏠',label:'Dashboard',key:'dashboard'},
    {href:'/case_file',icon:'🔍',label:'Search Cases',key:'search'},
  ];
  const byRole={
    PP:       [
      {href:'/application_form',icon:'➕',label:'New Application',key:'new_app'},
      {href:'/complaints',      icon:'📣',label:'My Complaints',  key:'complaints'},
    ],
    Scrutiny: [{href:'/scrutiny',icon:'🔍',label:'Scrutiny Queue',key:'scrutiny'}],
    MoM:      [
      {href:'/mom',      icon:'📋',label:'MoM Dashboard',key:'mom'},
      {href:'/meetings', icon:'📅',label:'Meetings',     key:'meetings'},
    ],
    Admin:    [
      {href:'/admin',             icon:'⚙️', label:'Admin Panel',     key:'admin'},
      {href:'/scrutiny',          icon:'🔍', label:'Scrutiny View',   key:'scrutiny'},
      {href:'/mom',               icon:'📋', label:'MoM View',        key:'mom'},
      {href:'/meetings',          icon:'📅', label:'Meetings',        key:'meetings'},
      {href:'/admin_complaints',  icon:'📣', label:'Complaints',      key:'admin_complaints'},
    ],
  };
  const links=[...all,...(byRole[userRole]||[])];

  const topbarHtml=`
    <div class="topbar">
      <div class="topbar-brand">
        <div class="brand-emblem">P3</div>
        <div class="brand-text">
          <h1>PARIVESH 3.0</h1>
          <p>Ministry of Environment, Forest &amp; Climate Change — Govt. of India</p>
        </div>
      </div>
      <div class="topbar-search">
        <span class="search-icon">🔍</span>
        <input id="global-search" placeholder="Search applications…" autocomplete="off">
      </div>
      <div class="topbar-right">
        <button class="notif-btn" onclick="toggleNotifPanel()" title="Notifications">
          🔔<span class="notif-badge" id="notif-badge" style="display:none">0</span>
        </button>
        <div class="user-chip" onclick="logout()" title="Sign out">
          <div class="user-avatar" id="user-avatar">?</div>
          <div>
            <div class="user-name" id="user-name">Loading…</div>
            <div class="user-role" id="user-role"></div>
          </div>
          <span style="opacity:.5;font-size:11px">⏻</span>
        </div>
      </div>
    </div>
    <div class="notif-panel" id="notif-panel">
      <div class="notif-panel-header">
        <span>🔔 Notifications</span>
        <button onclick="document.getElementById('notif-panel').classList.remove('open')" style="background:none;border:none;cursor:pointer;font-size:18px;color:var(--text-muted)">×</button>
      </div>
      <div class="notif-list" id="notif-list"></div>
    </div>`;

  const sidebarHtml=`
    <div class="sidebar">
      <div class="sidebar-section">
        <div class="sidebar-label">Navigation</div>
        ${links.map(l=>`<a href="${l.href}" class="sidebar-link ${activePage===l.key?'active':''}">
          <span class="sidebar-icon">${l.icon}</span>${l.label}</a>`).join('')}
      </div>
    </div>`;

  const chatbotHtml=`
    <button class="chatbot-fab" id="chatbot-fab" onclick="toggleChatbot()" title="PARIVESH Assistant">
      <span class="chatbot-fab-icon">💬</span>
    </button>
    <div class="chatbot-window" id="chatbot-window">
      <div class="chatbot-header">
        <div class="chatbot-header-left">
          <div class="chatbot-avatar">🌿</div>
          <div>
            <div class="chatbot-header-title">PARIVESH Assistant</div>
            <div class="chatbot-header-sub">● Online — AI-powered helper</div>
          </div>
        </div>
        <div class="chatbot-header-actions">
          <button onclick="document.getElementById('chat-messages').innerHTML='';_appendMsg('👋 Chat cleared! How can I help you?','bot')" title="Clear chat" class="chatbot-hdr-btn">🗑</button>
          <button class="chatbot-close chatbot-hdr-btn" onclick="toggleChatbot()">✕</button>
        </div>
      </div>
      <div class="chatbot-messages" id="chat-messages">
        <div class="chat-msg bot">👋 <strong>Hello! I'm the PARIVESH Assistant.</strong><br><br>
          I can answer questions about your application status, required documents, EDS, MoM, AI screening, and more.<br><br>
          <em>Type a question or tap a suggestion below.</em>
        </div>
        <div class="chat-chips" id="chat-welcome-chips">
          <button class="chat-chip" onclick="document.getElementById('chat-welcome-chips').remove();sendChatMsg('What is my application status?')">My status?</button>
          <button class="chat-chip" onclick="document.getElementById('chat-welcome-chips').remove();sendChatMsg('What documents do I need?')">Documents?</button>
          <button class="chat-chip" onclick="document.getElementById('chat-welcome-chips').remove();sendChatMsg('What does EDS mean?')">EDS?</button>
          <button class="chat-chip" onclick="document.getElementById('chat-welcome-chips').remove();sendChatMsg('How long will my application take?')">Timeline?</button>
        </div>
      </div>
      <div class="chatbot-input">
        <input id="chat-input" placeholder="Ask anything about your application…" autocomplete="off" maxlength="300">
        <button class="chatbot-send" onclick="sendChatMsg()" title="Send">➤</button>
      </div>
    </div>`;

  return {topbarHtml, sidebarHtml, chatbotHtml};
}
