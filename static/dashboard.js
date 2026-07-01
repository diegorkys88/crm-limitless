const API = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
  ? 'http://127.0.0.1:8000'
  : `${window.location.protocol}//${window.location.host}`;
let allContacts = [];
let allUsers    = [];
let allOutreach = [];
let allAppointments = [];
let currentContact = null;

// ── INIT ──────────────────────────────────────────────────────────────────────
async function loadData() {
  try {
    const h = authHeaders();
    const [contacts, appts, outreach, users] = await Promise.all([
      fetch(`${API}/contacts/?limit=1000`, {headers:h}).then(r => r.json()),
      fetch(`${API}/appointments/`, {headers:h}).then(r => r.json()),
      fetch(`${API}/outreach/`, {headers:h}).then(r => r.json()),
      fetch(`${API}/auth/users`, {headers:h}).then(r => r.json()).catch(() => []),
    ]);
    allUsers = Array.isArray(users) ? users : [];

    allContacts    = contacts;
    allAppointments = appts;
    allOutreach    = outreach;

    updateStats();
    renderDashboardContacts();
    renderDashboardAppts();
    renderActivityFeed();
    renderPipelineBars();

    document.getElementById('nav-badge').textContent =
      contacts.filter(c => c.status === 'pending').length || '—';

    // User info is set at login — don't overwrite from users list
  } catch(e) {
    console.error('Load error:', e);
  }
}

// ── STATS ─────────────────────────────────────────────────────────────────────
function updateStats() {
  document.getElementById('stat-total').textContent = allContacts.length;
  document.getElementById('stat-hot').textContent   = allContacts.filter(c => c.score === 'hot').length;
  document.getElementById('stat-warm').textContent  = allContacts.filter(c => c.score === 'warm').length;
  document.getElementById('stat-appts').textContent = allAppointments.filter(a => a.status === 'scheduled').length;
}

// ── NAVIGATION ────────────────────────────────────────────────────────────────
function showPage(page) {
  ['dashboard','contacts','outreach','appointments','sync','settings'].forEach(p => {
    document.getElementById(`page-${p}`).style.display = 'none';
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  });
  document.getElementById(`page-${page}`).style.display = 'block';
  document.getElementById('page-title').textContent = page.toUpperCase();

  const navItem = document.querySelector(`.nav-item[onclick="showPage('${page}')"]`);
  if (navItem) navItem.classList.add('active');

  if (page === 'contacts')     { currentContactPage = 1; renderContactsTable(allContacts, true); }
  if (page === 'outreach')     renderOutreachTable();
  if (page === 'appointments') renderAppointmentsTable();
  if (page === 'settings')     loadUsers();
}

// ── RENDER HELPERS ────────────────────────────────────────────────────────────
function scoreHTML(score) {
  if (!score) return '<span style="color:var(--muted);font-size:11px">—</span>';
  const map = { hot: '🔥', warm: '🟡', cold: '🔵' };
  return `<span class="score-badge score-${score}">${map[score] || ''} ${score.toUpperCase()}</span>`;
}

function statusHTML(status) {
  const map = {
    // Contact statuses
    pending:               ['Pending',      'status-pending'],
    outreach_sent:         ['Contacted',    'status-sent'],
    appointment_scheduled: ['Meeting Set',  'status-scheduled'],
    closed_won:            ['Won ✓',        'status-sent'],
    closed_lost:           ['Lost',         'status-pending'],
    // Outreach statuses
    draft:                 ['Draft',        'status-pending'],
    sent:                  ['Sent',         'status-sent'],
    opened:                ['Opened',       'status-scheduled'],
    clicked:               ['Clicked',      'status-scheduled'],
    bounced:               ['Bounced',      'status-pending'],
    pending_approval:      ['Pending',      'status-pending'],
    // Appointment statuses
    scheduled:             ['Scheduled',    'status-scheduled'],
    completed:             ['Completed',    'status-sent'],
    cancelled:             ['Cancelled',    'status-pending'],
    no_show:               ['No Show',      'status-pending'],
  };
  const [label, cls] = map[status] || [status || '—', 'status-pending'];
  return `<span class="status-pill ${cls}">${label}</span>`;
}

function initials(c) {
  return ((c.first_name || '?')[0] + (c.last_name || '?')[0]).toUpperCase();
}

function avatarColor(id) {
  const colors = ['#2a2a3a','#1a2a2a','#2a1a1a','#2a2a1a','#1a1a3a'];
  return colors[id.charCodeAt(0) % colors.length];
}

// ── DASHBOARD ─────────────────────────────────────────────────────────────────
function renderDashboardContacts() {
  const tbody = document.getElementById('dashboard-contacts-body');
  const recent = [...allContacts].reverse().slice(0, 8);
  if (!recent.length) {
    tbody.innerHTML = `<tr><td colspan="4"><div class="empty-state"><p>No contacts yet. Add one or import from Kajabi.</p></div></td></tr>`;
    return;
  }
  tbody.innerHTML = recent.map(c => `
    <tr onclick="openDetail('${c.id}')" class="fade-in">
      <td><div class="contact-cell">
        <div class="contact-avatar" style="background:${avatarColor(c.id)}">${initials(c)}</div>
        <div><div class="contact-name">${c.first_name || ''} ${c.last_name || ''}</div>
        <div class="contact-company">${c.company || '—'}</div></div>
      </div></td>
      <td>${scoreHTML(c.score)}</td>
      <td>${statusHTML(c.status)}</td>
      <td><span class="source-tag">${c.source || '—'}</span></td>
    </tr>`).join('');
}

function renderDashboardAppts() {
  const container = document.getElementById('dashboard-appts');
  const upcoming  = allAppointments.filter(a => a.status === 'scheduled').slice(0, 5);
  if (!upcoming.length) {
    container.innerHTML = `<div class="empty-state"><svg fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg><p>No upcoming meetings</p></div>`;
    return;
  }
  container.innerHTML = upcoming.map(a => {
    const contact  = allContacts.find(c => c.id === a.contact_id) || {};
    const dt       = a.scheduled_at ? new Date(a.scheduled_at) : null;
    const day      = dt ? dt.getDate() : '—';
    const month    = dt ? dt.toLocaleString('en', {month:'short'}).toUpperCase() : '';
    const time     = dt ? dt.toLocaleTimeString('en', {hour:'2-digit',minute:'2-digit'}) : '';
    return `<div class="appt-item">
      <div class="appt-date"><div class="appt-day">${day}</div><div class="appt-month">${month}</div></div>
      <div class="appt-info">
        <div class="appt-name">${contact.first_name || ''} ${contact.last_name || '—'}</div>
        <div class="appt-company">${contact.company || '—'}</div>
        <div class="appt-time">${time}</div>
        <div class="appt-score">${scoreHTML(contact.score)}</div>
      </div>
    </div>`;
  }).join('');
}

function renderActivityFeed() {
  const feed = document.getElementById('activity-feed');
  const items = [];
  allContacts.slice(-6).reverse().forEach(c => {
    items.push({ color: '#4a9eff', text: `<strong>${c.first_name} ${c.last_name}</strong> added from ${c.source}`, time: c.created_at });
  });
  allAppointments.slice(-3).forEach(a => {
    const c = allContacts.find(x => x.id === a.contact_id) || {};
    items.push({ color: '#2ecc71', text: `<strong>${c.first_name || ''} ${c.last_name || ''}</strong> booked a meeting`, time: a.created_at });
  });
  if (!items.length) {
    feed.innerHTML = `<div class="empty-state"><p>No recent activity</p></div>`;
    return;
  }
  feed.innerHTML = items.slice(0,8).map(i => `
    <div class="feed-item">
      <div class="feed-dot" style="background:${i.color}"></div>
      <div><div class="feed-text">${i.text}</div>
      <div class="feed-time">${i.time ? new Date(i.time).toLocaleString('en',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : ''}</div></div>
    </div>`).join('');
}

function renderPipelineBars() {
  const container = document.getElementById('pipeline-bars');
  const statuses  = ['pending','outreach_sent','appointment_scheduled'];
  const labels    = ['Pending','Contacted','Meeting Set'];
  const total     = allContacts.length || 1;
  container.innerHTML = statuses.map((s, i) => {
    const count = allContacts.filter(c => c.status === s).length;
    const pct   = Math.round((count / total) * 100);
    const colors= ['#888','#2ecc71','#4a9eff'];
    return `<div style="margin-bottom:16px">
      <div style="display:flex;justify-content:space-between;margin-bottom:6px">
        <span style="font-size:11px;color:var(--muted)">${labels[i]}</span>
        <span style="font-size:11px;color:var(--white);font-family:var(--font-mono)">${count}</span>
      </div>
      <div style="background:var(--gray2);height:4px;border-radius:2px">
        <div style="background:${colors[i]};height:4px;border-radius:2px;width:${pct}%;transition:width 0.5s ease"></div>
      </div>
    </div>`;
  }).join('');
}

// ── CONTACTS TABLE ────────────────────────────────────────────────────────────
let currentFilter = 'all';
let currentSearch = '';
let currentContactPage = 1;
const CONTACTS_PER_PAGE = 50;

function renderContactsTable(contacts, resetPage = false) {
  if (resetPage) currentContactPage = 1;

  const tbody    = document.getElementById('contacts-body');
  const total    = contacts.length;
  const pages    = Math.ceil(total / CONTACTS_PER_PAGE);
  const start    = (currentContactPage - 1) * CONTACTS_PER_PAGE;
  const end      = Math.min(start + CONTACTS_PER_PAGE, total);
  const paginated = contacts.slice(start, end);

  document.getElementById('contacts-count').textContent =
    `${total} contacts — page ${currentContactPage} of ${pages || 1}`;

  if (!paginated.length) {
    tbody.innerHTML = `<tr><td colspan="6"><div class="empty-state"><p>No contacts found</p></div></td></tr>`;
    renderPagination(contacts, 0);
    return;
  }

  tbody.innerHTML = paginated.map(c => `
    <tr onclick="openDetail('${c.id}')" class="fade-in">
      <td><div class="contact-cell">
        <div class="contact-avatar" style="background:${avatarColor(c.id)}">${initials(c)}</div>
        <div><div class="contact-name">${c.first_name || ''} ${c.last_name || ''}</div>
        <div class="contact-company">${c.email}</div></div>
      </div></td>
      <td style="color:var(--muted);font-size:12px">${c.title || '—'}</td>
      <td>${scoreHTML(c.score)}</td>
      <td>${statusHTML(c.status)}</td>
      <td><span class="source-tag">${c.source || '—'}</span></td>
      <td><button class="action-btn" onclick="event.stopPropagation();generateOutreachFor('${c.id}')">Outreach</button></td>
    </tr>`).join('');

  renderPagination(contacts, pages);
}

function renderPagination(contacts, pages) {
  // Remove existing pagination
  const existing = document.getElementById('contacts-pagination');
  if (existing) existing.remove();

  if (pages <= 1) return;

  const panel = document.querySelector('#page-contacts .panel');
  const pag = document.createElement('div');
  pag.id = 'contacts-pagination';
  pag.style.cssText = 'display:flex;align-items:center;justify-content:center;gap:8px;padding:14px 20px;border-top:1px solid var(--border)';

  const prevDisabled = currentContactPage <= 1 ? 'disabled style="opacity:0.4;cursor:default"' : '';
  const nextDisabled = currentContactPage >= pages ? 'disabled style="opacity:0.4;cursor:default"' : '';

  // Show max 5 page buttons around current page
  let pageButtons = '';
  const start = Math.max(1, currentContactPage - 2);
  const end   = Math.min(pages, currentContactPage + 2);

  if (start > 1) pageButtons += `<button class="action-btn" onclick="goToContactPage(1, event)">1</button><span style="color:var(--muted)">…</span>`;
  for (let i = start; i <= end; i++) {
    const active = i === currentContactPage ? 'style="background:var(--white);color:var(--black);border-color:var(--white)"' : '';
    pageButtons += `<button class="action-btn" ${active} onclick="goToContactPage(${i}, event)">${i}</button>`;
  }
  if (end < pages) pageButtons += `<span style="color:var(--muted)">…</span><button class="action-btn" onclick="goToContactPage(${pages}, event)">${pages}</button>`;

  pag.innerHTML = `
    <button class="action-btn" ${prevDisabled} onclick="goToContactPage(${currentContactPage - 1}, event)">← Prev</button>
    ${pageButtons}
    <button class="action-btn" ${nextDisabled} onclick="goToContactPage(${currentContactPage + 1}, event)">Next →</button>
  `;
  panel.appendChild(pag);
}

function goToContactPage(page, event) {
  if (event) event.stopPropagation();
  currentContactPage = page;
  applyFilters();
}

function filterContacts(filter, el) {
  currentFilter = filter;
  currentContactPage = 1;
  document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
  el.classList.add('active');
  applyFilters();
}

function searchContacts(val) {
  currentSearch = val.toLowerCase();
  currentContactPage = 1;
  applyFilters();
}

function applyFilters() {
  let filtered = allContacts;
  if (currentFilter !== 'all') {
    if (['hot','warm','cold'].includes(currentFilter)) {
      filtered = filtered.filter(c => c.score === currentFilter);
    } else if (currentFilter === 'outreach_sent') {
      // "Contacted" = outreach sent OR appointment scheduled (all contacted)
      filtered = filtered.filter(c =>
        c.status === 'outreach_sent' ||
        c.status === 'appointment_scheduled' ||
        c.status === 'closed_won' ||
        c.status === 'closed_lost'
      );
    } else {
      filtered = filtered.filter(c => c.status === currentFilter);
    }
  }
  if (currentSearch)
    filtered = filtered.filter(c =>
      `${c.first_name} ${c.last_name} ${c.email} ${c.company}`.toLowerCase().includes(currentSearch));
  renderContactsTable(filtered);
}

// ── OUTREACH TABLE ────────────────────────────────────────────────────────────
function renderOutreachTable() {
  const tbody = document.getElementById('outreach-body');
  if (!allOutreach.length) {
    tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><p>No outreach yet</p></div></td></tr>`;
    return;
  }
  tbody.innerHTML = allOutreach.map(o => {
    const c = allContacts.find(x => x.id === o.contact_id) || {};
    return `<tr class="fade-in">
      <td><div class="contact-cell">
        <div class="contact-avatar" style="background:${avatarColor(c.id || '0')}">${initials(c)}</div>
        <div><div class="contact-name">${c.first_name || ''} ${c.last_name || ''}</div>
        <div class="contact-company">${c.email || ''}</div></div>
      </div></td>
      <td style="font-size:12px;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${o.subject || '—'}</td>
      <td>${statusHTML(o.status)}</td>
      <td style="font-size:11px;color:var(--muted);font-family:var(--font-mono)">${o.sent_at ? new Date(o.sent_at).toLocaleDateString() : '—'}</td>
      <td>${o.status === 'draft'
        ? `<button class="action-btn" onclick="sendOutreach('${o.id}')">Send</button>`
        : '<span style="font-size:11px;color:var(--muted)">Sent</span>'}</td>
    </tr>`;
  }).join('');
}

// ── APPOINTMENTS TABLE ─────────────────────────────────────────────────────────
function renderAppointmentsTable() {
  const tbody = document.getElementById('appointments-body');
  if (!allAppointments.length) {
    tbody.innerHTML = `<tr><td colspan="5"><div class="empty-state"><p>No appointments yet</p></div></td></tr>`;
    return;
  }
  tbody.innerHTML = allAppointments.map(a => {
    const c  = allContacts.find(x => x.id === a.contact_id) || {};
    const dt = a.scheduled_at ? new Date(a.scheduled_at) : null;
    return `<tr onclick="openDetail('${c.id}')" class="fade-in">
      <td><div class="contact-cell">
        <div class="contact-avatar" style="background:${avatarColor(c.id||'0')}">${initials(c)}</div>
        <div><div class="contact-name">${c.first_name||''} ${c.last_name||''}</div>
        <div class="contact-company">${c.company||'—'}</div></div>
      </div></td>
      <td style="font-family:var(--font-mono);font-size:11px;color:var(--muted)">${dt ? dt.toLocaleString('en',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '—'}</td>
      <td style="font-size:12px;color:var(--muted)">${getUserName(a.assigned_to_id)}</td>
      <td>${statusHTML(a.status)}</td>
      <td>${a.ai_summary
        ? '<span style="font-size:11px;color:var(--green);font-family:var(--font-mono)">Ready ✓</span>'
        : '<span style="font-size:11px;color:var(--muted)">—</span>'}</td>
    </tr>`;
  }).join('');
}

// ── HELPERS ───────────────────────────────────────────────────────────────────
function getUserName(userId) {
  if (!userId) return '—';
  const user = allUsers.find(u => u.id === userId);
  return user ? user.name : '—';
}

// ── CONTACT DETAIL ────────────────────────────────────────────────────────────
function subscribedHTML(subscribed) {
  if (subscribed === 'true')  return '<span style="color:var(--green)">✓ Subscribed</span>';
  if (subscribed === 'false') return '<span style="color:var(--hot)">✗ Not subscribed</span>';
  return '<span style="color:var(--muted)">— Unknown</span>';
}

function openDetail(id) {
  currentContact = allContacts.find(c => c.id === id);
  if (!currentContact) return;
  const c = currentContact;
  document.getElementById('d-avatar').textContent  = initials(c);
  document.getElementById('d-avatar').style.background = avatarColor(c.id);
  document.getElementById('d-name').textContent    = `${c.first_name || ''} ${c.last_name || ''}`;
  document.getElementById('d-title').textContent   = `${c.title || '—'} · ${c.company || '—'}`;
  document.getElementById('d-email').textContent   = c.email;
  document.getElementById('d-company-input').value  = c.company  || '';
  document.getElementById('d-region-input').value   = c.region   || '';
  document.getElementById('d-title-input').value    = c.title    || '';
  document.getElementById('d-industry-input').value = c.industry || '';
  document.getElementById('d-source').textContent  = c.source || '—';
  document.getElementById('d-subscribed').innerHTML = subscribedHTML(c.subscribed);
  document.getElementById('d-score').innerHTML     = scoreHTML(c.score);
  document.getElementById('d-status').innerHTML    = statusHTML(c.status);
  document.getElementById('d-action-result').textContent = '';
  document.getElementById('d-save-btn').style.display = 'none';

  // Check for AI summary
  const appt = allAppointments.find(a => a.contact_id === id && a.ai_summary);
  if (appt) {
    document.getElementById('d-summary-section').style.display = 'block';
    document.getElementById('d-summary').textContent = appt.ai_summary;
  } else {
    document.getElementById('d-summary-section').style.display = 'none';
  }

  document.getElementById('detail-overlay').classList.add('open');
}

function checkDetailDirty() {
  if (!currentContact) return;
  const companyChanged  = document.getElementById('d-company-input').value  !== (currentContact.company  || '');
  const regionChanged   = document.getElementById('d-region-input').value   !== (currentContact.region   || '');
  const titleChanged    = document.getElementById('d-title-input').value    !== (currentContact.title    || '');
  const industryChanged = document.getElementById('d-industry-input').value !== (currentContact.industry || '');
  document.getElementById('d-save-btn').style.display =
    (companyChanged || regionChanged || titleChanged || industryChanged) ? 'block' : 'none';
}

async function saveContactDetails() {
  if (!currentContact) return;
  const company  = document.getElementById('d-company-input').value.trim();
  const region   = document.getElementById('d-region-input').value.trim();
  const title    = document.getElementById('d-title-input').value.trim();
  const industry = document.getElementById('d-industry-input').value.trim();
  const btn      = document.getElementById('d-save-btn');

  btn.disabled = true;
  btn.textContent = 'Saving...';

  try {
    const r = await fetch(`${API}/contacts/${currentContact.id}`, {
      method: 'PATCH',
      headers: authHeaders(),
      body: JSON.stringify({ company, region, title, industry })
    });
    if (r.ok) {
      showNotif('Saved', 'Contact details updated');
      btn.style.display = 'none';
      await loadData();
      currentContact = allContacts.find(c => c.id === currentContact.id);
    } else {
      const d = await r.json();
      showNotif('Error', d.detail || 'Could not save changes');
    }
  } catch (e) {
    showNotif('Error', 'Connection error while saving');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Save Changes';
  }
}

function closeDetail(e) {
  if (e.target === document.getElementById('detail-overlay')) closeDetailPanel();
}

function closeDetailPanel() {
  document.getElementById('detail-overlay').classList.remove('open');
  document.getElementById('d-email-preview').style.display = 'none';
  document.getElementById('d-email-preview').value         = '';
  document.getElementById('d-action-result').textContent   = '';
  document.getElementById('d-generate-btn').textContent    = 'Generate Outreach';
  document.getElementById('d-generate-btn').onclick        = generateOutreach;
  document.getElementById('d-title-input').value           = '';
  document.getElementById('d-industry-input').value        = '';
  currentContact = null;
}

// ── ACTIONS ───────────────────────────────────────────────────────────────────
async function generateOutreach() {
  if (!currentContact) return;
  const btn = document.getElementById('d-generate-btn');
  const res = document.getElementById('d-action-result');
  btn.textContent = 'Generating...';
  btn.disabled    = true;
  try {
    const r = await fetch(`${API}/outreach/generate/${currentContact.id}`, {method:'POST', headers:authHeaders()});
    const d = await r.json();
    if (r.ok) {
      res.style.color   = 'var(--green)';
      res.textContent   = `✓ Score: ${d.score?.score?.toUpperCase()} — ${d.score?.reason}\n\nSubject: ${d.subject}`;
      const preview = document.getElementById('d-email-preview');
      preview.style.display = 'block';
      preview.value         = d.body;
      // Add edit hint
      res.textContent = res.textContent + '\n\n✏️ You can edit the email above before sending.';
      btn.textContent   = 'Send Email';
      btn.onclick       = () => sendGeneratedOutreach(d.outreach_id);
      await loadData();
    } else {
      res.style.color = 'var(--hot)';
      res.textContent = d.detail || 'Error generating outreach';
    }
  } catch(e) {
    res.style.color = 'var(--hot)';
    res.textContent = 'Connection error';
  }
  btn.disabled = false;
}

async function generateOutreachFor(contactId) {
  const r = await fetch(`${API}/outreach/generate/${contactId}`, {method:'POST', headers:authHeaders()});
  const d = await r.json();
  if (r.ok) { showNotif('Email Generated', `Subject: ${d.subject}`); await loadData(); }
}

async function sendGeneratedOutreach(outreachId) {
  const res = document.getElementById('d-action-result');

  // Save edited body if user changed it
  const editedBody = document.getElementById('d-email-preview').value;
  if (editedBody) {
    await fetch(`${API}/outreach/${outreachId}`, {
      method: 'PATCH',
      headers: authHeaders(),
      body: JSON.stringify({body: editedBody})
    });
  }

  res.style.color = 'var(--muted)';
  res.textContent = 'Sending...';

  const r = await fetch(`${API}/outreach/${outreachId}/send?sender_name=Diego`, {method:'POST', headers:authHeaders()});
  const d = await r.json();
  if (r.ok) {
    res.style.color = 'var(--green)';
    res.textContent = `✓ Email sent to ${d.to}`;
    document.getElementById('d-email-preview').style.display = 'none';
    showNotif('Email Sent!', `Delivered to ${d.to}`);
    await loadData();
  } else {
    res.style.color = 'var(--hot)';
    res.textContent = d.detail || 'Error sending email';
  }
}

async function sendOutreach(outreachId) {
  const r = await fetch(`${API}/outreach/${outreachId}/send?sender_name=Diego`, {method:'POST', headers:authHeaders()});
  const d = await r.json();
  if (r.ok) { showNotif('Email Sent!', `Delivered successfully`); await loadData(); renderOutreachTable(); }
}

async function simulateBooking() {
  if (!currentContact) return;
  const res = document.getElementById('d-action-result');
  res.style.color = 'var(--muted)';
  res.textContent = 'Simulating booking...';
  const dt = new Date(); dt.setDate(dt.getDate() + 7);
  const iso = dt.toISOString().replace('.000Z','Z');
  try {
    const r = await fetch(`${API}/webhooks/calendly/simulate?contact_id=${currentContact.id}&scheduled_at=${iso}`, {method:'POST', headers:authHeaders()});
    const d = await r.json();
    if (r.ok) {
      res.style.color = 'var(--green)';
      res.textContent = `✓ Appointment created\nAI briefing generated\nAssigned to: ${d.assigned_to}`;
      showNotif('Meeting Booked!', `${currentContact.first_name} scheduled for ${new Date(iso).toLocaleDateString()}`);
      await loadData();
      const appt = allAppointments.find(a => a.id === d.appointment_id);
      if (appt?.ai_summary) {
        document.getElementById('d-summary-section').style.display = 'block';
        document.getElementById('d-summary').textContent = appt.ai_summary;
      }
    }
  } catch(e) {
    res.style.color = 'var(--hot)';
    res.textContent = 'Error simulating booking';
  }
}

async function enrichContact() {
  if (!currentContact) return;
  const res = document.getElementById('d-action-result');
  res.style.color = 'var(--muted)';
  res.textContent = 'Enriching with Apollo...';
  try {
    const r = await fetch(`${API}/sync/apollo/enrich/${currentContact.id}`, {method:'POST', headers:authHeaders()});
    const d = await r.json();
    res.style.color = d.status === 'enriched' ? 'var(--green)' : 'var(--muted)';
    res.textContent = d.status === 'enriched'
      ? `✓ Updated: ${d.updated_fields.join(', ')}`
      : 'No data found in Apollo';
    if (d.status === 'enriched') await loadData();
  } catch(e) {
    res.style.color = 'var(--hot)';
    res.textContent = 'Apollo enrichment error';
  }
}

// ── MODAL ─────────────────────────────────────────────────────────────────────
function openModal()  { document.getElementById('modal').classList.add('open'); }
function closeModal() { document.getElementById('modal').classList.remove('open'); }

async function createContact() {
  const email = document.getElementById('f-email').value.trim();
  if (!email) { alert('Email is required'); return; }
  const payload = {
    email,
    first_name: document.getElementById('f-first').value.trim() || null,
    last_name:  document.getElementById('f-last').value.trim()  || null,
    title:      document.getElementById('f-title').value.trim() || null,
    company:    document.getElementById('f-company').value.trim() || null,
    industry:   document.getElementById('f-industry').value.trim() || null,
    region:     document.getElementById('f-region').value.trim() || null,
    source:     document.getElementById('f-source').value,
  };
  const r = await fetch(`${API}/contacts/`, {method:'POST', headers:authHeaders(), body:JSON.stringify(payload)});
  if (r.ok) {
    closeModal();
    showNotif('Contact Created', `${payload.first_name || ''} ${payload.last_name || ''} added`);
    await loadData();
    if (document.getElementById('page-contacts').style.display !== 'none') renderContactsTable(allContacts);
  } else {
    const e = await r.json();
    alert(e.detail || 'Error creating contact');
  }
}

// ── SYNC ACTIONS ──────────────────────────────────────────────────────────────
async function runApolloSearch() {
  const region   = document.getElementById('apollo-region').value;
  const industry = document.getElementById('apollo-industry').value;
  const limit    = document.getElementById('apollo-limit').value;
  const res = document.getElementById('apollo-result');
  res.textContent = 'Searching...';
  const r = await fetch(`${API}/sync/apollo/search/sync?region=${encodeURIComponent(region)}&industry=${industry}&limit=${limit}&enrich=false`, {method:'POST', headers:authHeaders()});
  const d = await r.json();
  res.textContent = d.error ? `Error: ${d.error}` : `Found: ${d.found} | Approved: ${d.approved} | ${d.summary}`;
  await loadData();
}

async function runKajabiImport() {
  const limitInput = document.getElementById('kajabi-limit').value;
  const btn = document.getElementById('kajabi-import-btn');
  const res = document.getElementById('kajabi-result');

  btn.disabled = true;
  btn.textContent = 'Importing...';
  res.style.color = 'var(--muted)';

  const limit = limitInput ? parseInt(limitInput) : null;
  let totalImported = 0;
  let totalSkipped  = 0;
  let totalFound    = 0;
  let page = 1;
  const pageSize = 100;

  try {
    while (true) {
      const batchLimit = limit ? Math.min(pageSize, limit - totalFound) : pageSize;
      if (batchLimit <= 0) break;

      res.textContent = `Importing page ${page}... (${totalImported} imported so far)`;

      const r = await fetch(`${API}/sync/kajabi/import/sync?limit=${batchLimit}&page=${page}`, {
        method: 'POST', headers: authHeaders()
      });
      const d = await r.json();

      if (!r.ok) {
        res.style.color = 'var(--hot)';
        res.textContent = d.detail || 'Import failed';
        break;
      }

      totalFound    += d.found    || 0;
      totalImported += d.imported || 0;
      totalSkipped  += d.skipped  || 0;

      res.style.color = 'var(--green)';
      res.textContent = `✓ Page ${page} done — ${totalImported} imported, ${totalSkipped} skipped so far`;

    // Stop if no contacts returned or no more pages
    if (!d.found || d.found === 0) break;
    if (!d.meta?.has_next) break;
    if (limit && totalFound >= limit) break;

      page++;
    }

    res.textContent = `✓ Import complete — Found: ${totalFound} | Imported: ${totalImported} | Skipped: ${totalSkipped}`;
    showNotif('Kajabi Import Complete', `${totalImported} new contacts added`);
    await loadData();

  } catch (e) {
    res.style.color = 'var(--hot)';
    res.textContent = 'Connection error during import';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Import from Kajabi';
  }
}

// ── NOTIFICATION ──────────────────────────────────────────────────────────────
function showNotif(title, body) {
  document.getElementById('notif-title').textContent = title;
  document.getElementById('notif-body').textContent  = body;
  const n = document.getElementById('notif');
  n.style.display = 'flex';
  setTimeout(() => { n.style.display = 'none'; }, 5000);
}

// ── AUTH ──────────────────────────────────────────────────────────────────────
let currentUserData = null;

function getToken()    { return localStorage.getItem('crm_token'); }
function setToken(t)   { localStorage.setItem('crm_token', t); }
function clearToken()  {
  localStorage.removeItem('crm_token');
  localStorage.removeItem('crm_user');
}
function getSavedUser() {
  try { return JSON.parse(localStorage.getItem('crm_user')); } catch(e) { return null; }
}
function saveUser(u) { localStorage.setItem('crm_user', JSON.stringify(u)); }

function authHeaders() {
  const token = getToken();
  return token ? { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' } : { 'Content-Type': 'application/json' };
}

async function doLogin() {
  const email    = document.getElementById('login-email').value.trim();
  const password = document.getElementById('login-password').value;
  const errEl    = document.getElementById('login-error');
  errEl.textContent = '';

  if (!email || !password) { errEl.textContent = 'Email and password required'; return; }

  try {
    const r = await fetch(`${API}/auth/login`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({email, password})
    });
    const d = await r.json();
    if (r.ok) {
      setToken(d.access_token);
      currentUserData = d.user;
      saveUser(d.user);
      showApp();
    } else {
      errEl.textContent = d.detail || 'Invalid email or password';
    }
  } catch(e) {
    errEl.textContent = 'Connection error — is the server running?';
  }
}

function showApp() {
  document.getElementById('login-screen').style.display = 'none';
  if (currentUserData) {
    document.getElementById('user-name').textContent    = currentUserData.name;
    document.getElementById('user-initial').textContent = currentUserData.name[0].toUpperCase();

    // Remove old role badge if exists (avoid duplicates on F5)
    const oldBadge = document.querySelector('.role-badge');
    if (oldBadge) oldBadge.remove();

    // Show role badge
    const roleEl = document.createElement('span');
    roleEl.className = `role-badge role-${currentUserData.role}`;
    roleEl.textContent = currentUserData.role === 'admin' ? 'ADMIN' : 'SALES';
    document.getElementById('user-name').after(roleEl);

    // Show admin nav, hide sync for sales reps
    if (currentUserData.role === 'admin') {
      document.getElementById('nav-section-admin').style.display = 'block';
      document.getElementById('nav-settings').style.display      = 'flex';
    } else {
      document.querySelector(".nav-item[onclick=\"showPage('sync')\"]").style.display = 'none';
    }
  }
  loadData();
}

function logout() {
  clearToken();
  currentUserData = null;
  document.getElementById('login-screen').style.display = 'flex';
}

async function checkAuth() {
  const token     = getToken();
  const savedUser = getSavedUser();

  if (!token) {
    document.getElementById('login-screen').style.display = 'flex';
    return;
  }

  // If we have saved user data — show app immediately (no flash)
  if (savedUser) {
    currentUserData = savedUser;
    showApp();
  }

  // Verify token in background — silently update or logout if expired
  try {
    const r = await fetch(`${API}/auth/me`, { headers: authHeaders() });
    if (r.ok) {
      const d = await r.json();
      currentUserData = d;
      saveUser(d);
      // Update UI if name/role changed
      document.getElementById('user-name').textContent    = d.name;
      document.getElementById('user-initial').textContent = d.name[0].toUpperCase();
    } else {
      // Token expired — logout
      clearToken();
      currentUserData = null;
      document.getElementById('login-screen').style.display = 'flex';
    }
  } catch(e) {
    // Server unreachable — keep showing app with cached data
    console.warn('Could not verify token — using cached session');
  }
}

// ── START ─────────────────────────────────────────────────────────────────────
// ── DETAIL FIELD LISTENERS ──────────────────────────────────────────────────
document.getElementById('d-company-input')?.addEventListener('input', checkDetailDirty);
document.getElementById('d-region-input')?.addEventListener('input', checkDetailDirty);
document.getElementById('d-title-input')?.addEventListener('input', checkDetailDirty);
document.getElementById('d-industry-input')?.addEventListener('input', checkDetailDirty);

checkAuth();
setInterval(() => { if(getToken()) loadData(); }, 30000);

// ── USER MANAGEMENT ──────────────────────────────────────────────────────────
async function createUser() {
  const name     = document.getElementById('new-user-name').value.trim();
  const email    = document.getElementById('new-user-email').value.trim();
  const password = document.getElementById('new-user-password').value;
  const role     = document.getElementById('new-user-role').value;
  const res      = document.getElementById('create-user-result');

  if (!name || !email || !password) {
    res.style.color = 'var(--hot)';
    res.textContent = 'All fields are required';
    return;
  }
  if (password.length < 8) {
    res.style.color = 'var(--hot)';
    res.textContent = 'Password must be at least 8 characters';
    return;
  }

  res.style.color = 'var(--muted)';
  res.textContent = 'Creating...';

  const r = await fetch(`${API}/auth/register`, {
    method:  'POST',
    headers: authHeaders(),
    body:    JSON.stringify({name, email, password, role})
  });
  const d = await r.json();

  if (r.ok) {
    res.style.color = 'var(--green)';
    res.textContent = `✓ User ${d.name} created as ${d.role}`;
    document.getElementById('new-user-name').value     = '';
    document.getElementById('new-user-email').value    = '';
    document.getElementById('new-user-password').value = '';
    loadUsers();
  } else {
    res.style.color = 'var(--hot)';
    res.textContent = d.detail || 'Error creating user';
  }
}

async function loadUsers() {
  const container = document.getElementById('users-list');
  if (!container) return;

  const r = await fetch(`${API}/auth/users`, {headers: authHeaders()});
  if (!r.ok) { container.innerHTML = '<div class="empty-state"><p>Could not load users</p></div>'; return; }
  const users = await r.json();

  if (!users.length) {
    container.innerHTML = '<div class="empty-state"><p>No users yet</p></div>';
    return;
  }

  container.innerHTML = users.map(u => `
    <div style="padding:12px 20px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:10px">
      <div class="contact-avatar" style="background:var(--gray3);font-size:11px">${u.name[0].toUpperCase()}</div>
      <div style="flex:1">
        <div style="font-size:13px;font-weight:500;color:var(--white)">${u.name}</div>
        <div style="font-size:11px;color:var(--muted)">${u.email}</div>
      </div>
      <span class="role-badge role-${u.role}">${u.role === 'admin' ? 'ADMIN' : 'SALES'}</span>
      ${u.is_active === 'false'
        ? '<span style="font-size:10px;color:var(--hot);font-family:var(--font-mono)">INACTIVE</span>'
        : `<button class="action-btn" onclick="deactivateUser('${u.id}','${u.name}')">Deactivate</button>`
      }
    </div>`).join('');
}

async function deactivateUser(userId, userName) {
  if (!confirm(`Deactivate ${userName}? They will no longer be able to log in.`)) return;
  const r = await fetch(`${API}/auth/users/${userId}/deactivate`, {method:'PATCH', headers:authHeaders()});
  if (r.ok) { showNotif('User deactivated', `${userName} can no longer log in`); loadUsers(); }
}

async function changePassword() {
  const cur     = document.getElementById('cur-password').value;
  const newPw   = document.getElementById('new-password').value;
  const confirm = document.getElementById('confirm-password').value;
  const res     = document.getElementById('change-pw-result');

  if (!cur || !newPw || !confirm) { res.style.color='var(--hot)'; res.textContent='All fields required'; return; }
  if (newPw !== confirm)           { res.style.color='var(--hot)'; res.textContent='Passwords do not match'; return; }
  if (newPw.length < 8)            { res.style.color='var(--hot)'; res.textContent='Min 8 characters'; return; }

  const r = await fetch(`${API}/auth/me/password`, {
    method:  'PATCH',
    headers: authHeaders(),
    body:    JSON.stringify({current_password: cur, new_password: newPw})
  });
  const d = await r.json();

  if (r.ok) {
    res.style.color = 'var(--green)';
    res.textContent = '✓ Password updated';
    document.getElementById('cur-password').value     = '';
    document.getElementById('new-password').value     = '';
    document.getElementById('confirm-password').value = '';
  } else {
    res.style.color = 'var(--hot)';
    res.textContent = d.detail || 'Error updating password';
  }
}

// ── CLOSE CONTACT ────────────────────────────────────────────────────────────
async function closeContact(result) {
  if (!currentContact) return;
  const label = result === 'won' ? 'Close Won' : 'Close Lost';
  if (!confirm(`Mark ${currentContact.first_name} ${currentContact.last_name} as ${label}?`)) return;

  const res = document.getElementById('d-action-result');
  res.style.color = 'var(--muted)';
  res.textContent = 'Updating...';

  try {
    // Update status in CRM
    const newStatus = result === 'won' ? 'closed_won' : 'closed_lost';
    const r = await fetch(`${API}/contacts/${currentContact.id}`, {
      method: 'PATCH',
      headers: authHeaders(),
      body: JSON.stringify({status: newStatus})
    });

    if (r.ok) {
      // Add crm-closed tag in Kajabi
      if (result === 'won') {
        await fetch(`${API}/sync/kajabi/tag/${currentContact.id}?tag_name=crm-closed`, {
          method: 'POST', headers: authHeaders()
        });
      }
      res.style.color = result === 'won' ? 'var(--green)' : 'var(--hot)';
      res.textContent = `✓ Marked as ${label}`;
      showNotif(label, `${currentContact.first_name} ${currentContact.last_name} — ${label}`);
      await loadData();
      closeDetailPanel();
    }
  } catch (e) {
    res.style.color = 'var(--hot)';
    res.textContent = 'Error updating contact';
  }
}

// ── MOBILE ────────────────────────────────────────────────────────────────────
function toggleSidebar() {
  document.querySelector('.sidebar').classList.toggle('open');
  document.getElementById('sidebar-overlay').classList.toggle('open');
}

function closeSidebar() {
  document.querySelector('.sidebar').classList.remove('open');
  document.getElementById('sidebar-overlay').classList.remove('open');
}

function showPageMobile(page, el) {
  showPage(page);
  document.querySelectorAll('.bottom-nav-item').forEach(b => b.classList.remove('active'));
  el.classList.add('active');
  closeSidebar();
}

// Close sidebar when nav item clicked on mobile
document.querySelectorAll('.nav-item').forEach(item => {
  item.addEventListener('click', () => {
    if (window.innerWidth <= 768) closeSidebar();
  });
});