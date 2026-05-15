const API = window.location.origin;

let token = localStorage.getItem('token');
let role = localStorage.getItem('role');
let fullName = localStorage.getItem('fullName');
let userAirportId = localStorage.getItem('userAirportId') ? parseInt(localStorage.getItem('userAirportId')) : null;
let selectedAirport = null;
let allFlights = [];
let activeTerminal = 'ALL';
let activeAirline = 'ALL';
let selectedAirline = null;
let activeCategory = 'arrival';
let lastFlightCategory = 'arrival'; // remembers last real tab (arrival/departure)
let activeStatusFilter = 'ALL'; // stat-card status filter (ALL | Arrived | Boarding | Scheduled | Delayed)
let refreshTimer = null;
let currentCarouselFlightId = null;

const AIRPORT_ICONS = { DEL: '<img src="/static/delhi.jpg" style="width:100%;height:100%;object-fit:cover;">', BOM: '<img src="/static/mumbai.jpg" style="width:100%;height:100%;object-fit:cover;">', NMIA: '<img src="/static/nmia.jpg" style="width:100%;height:100%;object-fit:cover;">', BLR: '<img src="/static/banglore.jpg" style="width:100%;height:100%;object-fit:cover;">', HYD: '<img src="/static/hyderabad.jpg" style="width:100%;height:100%;object-fit:cover;">' };

// ── Page Router ──────────────────────────────────────────────────
// Handles single-page application (SPA) routing by hiding all sections
// and displaying only the requested page section.
function showPage(name) {
    // Hide ALL pages first
    document.querySelectorAll('.page').forEach(p => {
        p.classList.remove('active');
    });

    // Show target page
    const pg = document.getElementById('page-' + name);
    if (!pg) return;
    pg.classList.add('active');

    // Navbar: hide on landing and login, show on protected pages
    const navbar = document.getElementById('main-navbar');
    if (name === 'landing' || name === 'login') {
        navbar.classList.add('hidden');
    } else {
        navbar.classList.remove('hidden');
    }

    // Stop flight refresh when leaving flights page
    if (refreshTimer) {
        clearInterval(refreshTimer);
        refreshTimer = null;
    }

    // Scroll to top
    window.scrollTo(0, 0);

    // Update active nav link
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.remove('active-link');
        // If the onclick contains showPage('name'), mark it active
        if (link.getAttribute('onclick') === `showPage('${name}')`) {
            link.classList.add('active-link');
        }
    });

    // Page-specific setup
    if (name === 'airports') loadAirports();
    if (name === 'admin-profile') {
        if (role !== 'admin') { showPage('airports'); return; }
        document.getElementById('admin-current-password').value = '';
        document.getElementById('admin-new-password').value = '';
        document.getElementById('admin-confirm-password').value = '';
        const msgBox = document.getElementById('admin-msg-pw');
        if (msgBox) msgBox.style.display = 'none';
        
        const menu = document.getElementById('nav-user-menu');
        const wrap = document.getElementById('nav-user-wrap');
        if (menu) menu.classList.remove('open');
        if (wrap) wrap.classList.remove('open');
        
        loadAdminProfile();
    }
    if (name === 'register') { if (role !== 'admin') { showPage('airports'); return; } loadUsers(); loadRegisterAirports(); }
    if (name === 'flights') {
        if (!selectedAirport) { showPage('airports'); return; }
        setupFlightPage();
        fetchFlights();
        refreshTimer = setInterval(fetchFlights, 5000);
    }
    if (name === 'analytics') {
        if (role !== 'admin' && role !== 'staff') { showPage('airports'); return; }
        loadAnalytics();
        refreshTimer = setInterval(loadAnalytics, 5000);
    }
}

// ── Auth ─────────────────────────────────────────────────────────
async function handleLogin() {
    const errEl = document.getElementById('login-error');
    const btn = document.getElementById('login-btn');
    errEl.style.display = 'none';
    btn.textContent = 'Signing in...';
    btn.disabled = true;

    const username = document.getElementById('login-username').value.trim();
    const password = document.getElementById('login-password').value;

    try {
        const res = await fetch(`${API}/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password }),
        });
        if (!res.ok) {
            const e = await res.json();
            throw new Error(e.detail || 'Login failed');
        }
        const data = await res.json();
        token = data.access_token;
        role = data.role;
        fullName = data.full_name;
        localStorage.setItem('token', token);
        localStorage.setItem('role', role);
        localStorage.setItem('fullName', fullName);
        localStorage.setItem('username', data.username);
        // Store airport_id for staff/viewer scoping
        userAirportId = data.airport_id || null;
        if (userAirportId) localStorage.setItem('userAirportId', userAirportId);
        else localStorage.removeItem('userAirportId');
        setupNavbar();
        showPage('airports');
    } catch (err) {
        errEl.textContent = err.message;
        errEl.style.display = 'block';
    } finally {
        btn.textContent = 'Sign In';
        btn.disabled = false;
    }
}

function handleLogout() {
    localStorage.clear();
    token = role = fullName = null;
    userAirportId = null;
    selectedAirport = null;
    showPage('landing');
}

function setupNavbar() {
    document.getElementById('nav-fullname').textContent = fullName || '';
    const badge = document.getElementById('nav-role-badge');
    badge.textContent = role || '';
    badge.className = 'role-badge role-' + (role || '');
    const regLink      = document.getElementById('nav-register-link');
    const analyticsLink = document.getElementById('nav-analytics-link');
    if (role === 'admin') {
        regLink.classList.remove('hidden');
    } else {
        regLink.classList.add('hidden');
    }
    if (role === 'admin' || role === 'staff') {
        if (analyticsLink) analyticsLink.classList.remove('hidden');
    } else {
        if (analyticsLink) analyticsLink.classList.add('hidden');
    }

    // ── User pill dropdown visibility ──
    // admin: show the informational "⚙ Admin Account" item (non-clickable)
    // staff / viewer / other: show the "🔒 Change Password" item
    const changePwItem = document.getElementById('nav-changepw-item');
    const adminInfo    = document.getElementById('nav-admin-info');
    if (role === 'admin') {
        if (changePwItem) changePwItem.classList.add('hidden');
        if (adminInfo)    adminInfo.style.display = 'flex';
    } else {
        if (changePwItem) changePwItem.classList.remove('hidden');
        if (adminInfo)    adminInfo.style.display = 'none';
    }
}

// ── Nav user pill dropdown ──────────────────────────────────────
function toggleUserPillMenu(event) {
    event.stopPropagation();
    const wrap = document.getElementById('nav-user-wrap');
    const menu = document.getElementById('nav-user-menu');
    const isOpen = menu.classList.contains('open');
    // Close any other dropdowns (user-action menus)
    document.querySelectorAll('.user-action-menu.show').forEach(m => m.classList.remove('show'));
    if (isOpen) {
        menu.classList.remove('open');
        wrap.classList.remove('open');
    } else {
        menu.classList.add('open');
        wrap.classList.add('open');
    }
}

// Close the pill dropdown when clicking anywhere outside it
document.addEventListener('click', (e) => {
    const wrap = document.getElementById('nav-user-wrap');
    const menu = document.getElementById('nav-user-menu');
    if (wrap && menu && !wrap.contains(e.target)) {
        menu.classList.remove('open');
        wrap.classList.remove('open');
    }
});

// ── Change Password Modal ───────────────────────────────────

/** Open the change-password modal and reset all fields/messages. */
function openChangePwModal() {
    // Close the nav pill dropdown first
    const menu = document.getElementById('nav-user-menu');
    const wrap = document.getElementById('nav-user-wrap');
    if (menu) menu.classList.remove('open');
    if (wrap) wrap.classList.remove('open');

    // Reset all fields
    ['cpw-current', 'cpw-new', 'cpw-confirm'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });

    // Hide message + strength meter
    setCpwMsg('', '');
    const sw = document.getElementById('cpw-strength-wrap');
    if (sw) sw.style.display = 'none';
    const fill = document.getElementById('cpw-strength-fill');
    if (fill) { fill.style.width = '0%'; fill.style.background = ''; }

    // Re-enable submit button
    const btn = document.getElementById('cpw-submit-btn');
    if (btn) btn.disabled = false;

    // Show the modal overlay
    const overlay = document.getElementById('modal-changepw');
    if (overlay) overlay.classList.add('open');

    // Focus the first field
    setTimeout(() => {
        const cur = document.getElementById('cpw-current');
        if (cur) cur.focus();
    }, 80);
}

/** Close the change-password modal. */
function closeChangePwModal() {
    const overlay = document.getElementById('modal-changepw');
    if (overlay) overlay.classList.remove('open');
}

/** Allow clicking the dark overlay (but not the modal card) to close. */
function closeCpwModalOnBackdrop(event) {
    if (event.target.id === 'modal-changepw') closeChangePwModal();
}

/**
 * updatePwStrength(value)
 * Drives the password strength meter under the "New Password" field.
 * Scores the password by length, upper/lower case, digits, and symbols.
 */
function updatePwStrength(value) {
    const wrap  = document.getElementById('cpw-strength-wrap');
    const fill  = document.getElementById('cpw-strength-fill');
    const label = document.getElementById('cpw-strength-label');
    if (!wrap || !fill || !label) return;

    if (!value) {
        wrap.style.display = 'none';
        return;
    }
    wrap.style.display = 'flex';

    let score = 0;
    if (value.length >= 6)  score++;
    if (value.length >= 10) score++;
    if (/[A-Z]/.test(value)) score++;
    if (/[0-9]/.test(value)) score++;
    if (/[^A-Za-z0-9]/.test(value)) score++;

    const levels = [
        { pct: '20%',  bg: '#ef4444', text: 'Weak',      color: '#ef4444' },
        { pct: '40%',  bg: '#f97316', text: 'Fair',      color: '#f97316' },
        { pct: '60%',  bg: '#eab308', text: 'Good',      color: '#eab308' },
        { pct: '80%',  bg: '#22c55e', text: 'Strong',    color: '#22c55e' },
        { pct: '100%', bg: '#10b981', text: 'Very Strong', color: '#10b981' },
    ];
    const lvl = levels[Math.max(0, Math.min(score - 1, 4))];
    fill.style.width      = lvl.pct;
    fill.style.background = lvl.bg;
    label.textContent     = lvl.text;
    label.style.color     = lvl.color;
}

/**
 * setCpwMsg(text, type)
 * Shows a feedback message ('success' or 'error') inside the modal,
 * or hides the bar when text is empty.
 */
function setCpwMsg(text, type) {
    const el = document.getElementById('cpw-msg');
    if (!el) return;
    if (!text) {
        el.style.display = 'none';
        el.textContent   = '';
        el.className     = 'cpw-msg';
        return;
    }
    el.textContent   = text;
    el.className     = `cpw-msg msg-${type}`;
    el.style.display = 'block';
}

/**
 * Validates a password against strong security rules.
 * Returns an error string if invalid, or null if valid.
 */
function validateStrongPassword(pw, username = '', email = '', fullName = '') {
    if (pw.length < 8) return 'Password must be at least 8 characters.';
    if (!/[A-Z]/.test(pw)) return 'Password must contain at least one uppercase letter.';
    if (!/[a-z]/.test(pw)) return 'Password must contain at least one lowercase letter.';
    if (!/\d/.test(pw)) return 'Password must contain at least one number.';
    if (!/[^a-zA-Z0-9]/.test(pw)) return 'Password must contain at least one special character.';
    
    const lowerPw = pw.toLowerCase();
    if (username && lowerPw.includes(username.toLowerCase())) return 'Password must not contain the username.';
    if (email && lowerPw.includes(email.split('@')[0].toLowerCase())) return 'Password must not contain the email address.';
    if (fullName) {
        const parts = fullName.toLowerCase().split(' ');
        for (const part of parts) {
            if (part.length > 2 && lowerPw.includes(part)) return 'Password must not contain parts of your name.';
        }
    }
    return null;
}

/**
 * submitChangePw()
 * Validates the form fields client-side, then calls
 * PUT /auth/me/change-password with { current_password, new_password }.
 * On success: closes modal after 1.5 s and shows a toast notification.
 * On failure: displays the server-returned error message inline.
 */
async function submitChangePw() {
    const current = document.getElementById('cpw-current').value;
    const newPw   = document.getElementById('cpw-new').value;
    const confirm = document.getElementById('cpw-confirm').value;
    const btn     = document.getElementById('cpw-submit-btn');

    // ── Client-side validation ──
    if (!current) {
        setCpwMsg('Please enter your current password.', 'error'); return;
    }
    
    // User info for validation (from localStorage)
    const storedUsername = localStorage.getItem('username') || '';
    const storedEmail = localStorage.getItem('email') || '';
    
    const pwError = validateStrongPassword(newPw, storedUsername, storedEmail, fullName);
    if (pwError) {
        setCpwMsg(pwError, 'error'); return;
    }
    if (newPw !== confirm) {
        setCpwMsg('New passwords do not match.', 'error'); return;
    }
    if (current === newPw) {
        setCpwMsg('New password must differ from the current one.', 'error'); return;
    }

    // ── Submit to backend ──
    btn.disabled     = true;
    btn.textContent  = 'Updating…';

    try {
        const res = await fetch(`${API}/auth/me/change-password`, {
            method:  'PUT',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body:    JSON.stringify({
                current_password: current,
                new_password:     newPw,
            }),
        });

        if (!res.ok) {
            const e = await res.json().catch(() => ({}));
            throw new Error(parseApiError(e, 'Password update failed'));
        }

        // ── Success ──
        setCpwMsg('✓ Password updated successfully! An admin has been notified.', 'success');
        showToast('Password changed successfully', 'success');

        // Auto-close after 1.5 s
        setTimeout(closeChangePwModal, 1500);

    } catch (err) {
        setCpwMsg(err.message, 'error');
        btn.disabled    = false;
        btn.textContent = 'Update Password';
    }
}

// ── Register Helper: Toggle airport field based on role ────────────
function toggleAirportField() {
    const roleVal = document.getElementById('r-role').value;
    const airportGroup = document.getElementById('r-airport-group');
    if (roleVal === 'admin') {
        airportGroup.style.display = 'none';
        document.getElementById('r-airport').value = '';
    } else {
        airportGroup.style.display = '';
    }
}

async function loadRegisterAirports() {
    try {
        const res = await fetch(`${API}/airports`, { headers: authHeaders() });
        if (!res.ok) return;
        const airports = await res.json();
        const sel = document.getElementById('r-airport');
        sel.innerHTML = '<option value="">Select Airport\u2026</option>';
        airports.forEach(a => {
            const opt = document.createElement('option');
            opt.value = a.id;
            opt.textContent = `${a.name} (${a.code})`;
            sel.appendChild(opt);
        });
    } catch (err) { console.error(err); }
}

// ── Airports ──────────────────────────────────────────────────────
async function loadAirports() {
    try {
        const res = await fetch(`${API}/airports`, { headers: authHeaders() });
        if (res.status === 401) { handleLogout(); return; }
        const airports = await res.json();

        // Staff/Viewer: auto-select their assigned airport and skip the grid
        if ((role === 'staff' || role === 'viewer') && userAirportId) {
            const myAirport = airports.find(a => a.id === userAirportId);
            if (myAirport) {
                selectedAirport = myAirport;
                localStorage.setItem('selectedAirport', JSON.stringify(myAirport));
                showPage('flights');
                return;
            }
        }

        const grid = document.getElementById('airports-grid');
        grid.innerHTML = '';

        // Render cards first with a loading placeholder for stats
        airports.forEach(a => {
            const card = document.createElement('div');
            card.className = 'airport-card';
            card.id = `airport-card-${a.id}`;
            card.innerHTML = `
<div class="airport-card-img-wrapper">
  <div class="airport-card-img">${AIRPORT_ICONS[a.code] || '✈️'}</div>
</div>
<div class="airport-card-body">
  <span class="airport-code-badge">${a.code}</span>
  <h3>${a.name}</h3>
  <p class="text-muted">${a.city}</p>
</div>`;
            card.onclick = () => {
                selectedAirport = a;
                localStorage.setItem('selectedAirport', JSON.stringify(a));
                showPage('flights');
            };
            grid.appendChild(card);
        });


    } catch (err) { console.error(err); }
}

// ── Register ──────────────────────────────────────────────────────
async function handleRegister() {
    const successEl = document.getElementById('reg-success');
    const errorEl = document.getElementById('reg-error');
    const btn = document.getElementById('register-btn');
    successEl.style.display = errorEl.style.display = 'none';

    const password = document.getElementById('r-password').value;
    const confirm = document.getElementById('r-confirm').value;
    if (password !== confirm) {
        errorEl.textContent = 'Passwords do not match';
        errorEl.style.display = 'block';
        return;
    }

    const selectedRole = document.getElementById('r-role').value;
    const airportIdRaw = document.getElementById('r-airport').value;
    const airportId = airportIdRaw ? parseInt(airportIdRaw) : null;

    // Validate: staff/viewer must have an airport
    if ((selectedRole === 'staff' || selectedRole === 'viewer') && !airportId) {
        errorEl.textContent = 'An airport must be assigned for staff and viewer roles';
        errorEl.style.display = 'block';
        return;
    }

    btn.textContent = 'Registering...';
    btn.disabled = true;

    const payload = {
        full_name: document.getElementById('r-fullname').value.trim(),
        email: document.getElementById('r-email').value.trim(),
        username: document.getElementById('r-username').value.trim(),
        password,
        role: selectedRole,
        airport_id: selectedRole === 'admin' ? null : airportId,
    };

    try {
        const res = await fetch(`${API}/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify(payload),
        });
        if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed'); }
        successEl.textContent = `User "${payload.username}" registered! Credentials sent to ${payload.email}.`;
        successEl.style.display = 'block';
        document.getElementById('r-fullname').value = '';
        document.getElementById('r-email').value = '';
        document.getElementById('r-username').value = '';
        document.getElementById('r-password').value = '';
        document.getElementById('r-confirm').value = '';
        document.getElementById('r-airport').value = '';
        loadUsers();
    } catch (err) {
        errorEl.textContent = err.message;
        errorEl.style.display = 'block';
    } finally {
        btn.textContent = 'Register & Send Email';
        btn.disabled = false;
    }
}

async function loadUsers() {
    try {
        const res = await fetch(`${API}/users`, { headers: authHeaders() });
        if (!res.ok) return;
        const users = await res.json();
        const tbody = document.getElementById('users-tbody');
        tbody.innerHTML = '';
        users.filter(u => u.role !== 'admin').forEach(u => {
            const tr = document.createElement('tr');
            const statusIndicator = u.is_active === false
                ? '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#ef4444;margin-right:6px;" title="Inactive"></span>'
                : '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:#10b981;margin-right:6px;" title="Active"></span>';

            // ── Role-based dropdown items ──────────────────────────────────
            // Admin-role users: only the original prompt-based Edit + Reset Password.
            // All other roles (staff, viewer, operator, …): new full-page edit view.
            let menuItems;
            if (u.role === 'admin') {
                // Original behaviour — kept exactly as before for admin accounts
                menuItems = `<div onclick="editUser(${u.id},'${u.username}')">Edit</div>
                             <div onclick="resetPassword(${u.id},'${u.username}')">Reset Password</div>`;
            } else {
                // New full-page edit view for non-admin users
                menuItems = `<div onclick="openUserEdit(${u.id})">Edit</div>`;
            }

            tr.innerHTML = `
<td>${statusIndicator}${u.full_name}</td>
<td style="font-family:var(--mono);color:var(--cyan)">${u.username}</td>
<td>${u.email}</td>
<td><span class="role-badge role-${u.role}">${u.role}</span></td>
<td style="font-family:var(--mono);color:var(--text3);font-size:12px">${u.airport_id ? 'Airport #' + u.airport_id : '<em>All Airports</em>'}</td>
<td>
  <div class="user-action-dropdown">
    <button class="user-action-btn" onclick="toggleUserMenu(event,${u.id})">Actions &#9662;</button>
    <div class="user-action-menu" id="user-menu-${u.id}">
      ${menuItems}
    </div>
  </div>
</td>`;
            tbody.appendChild(tr);
        });
    } catch (err) { console.error(err); }
}

function toggleUserMenu(event, userId) {
    event.stopPropagation();
    const menu = document.getElementById(`user-menu-${userId}`);
    const isOpen = menu.classList.contains('show');
    // Close all open menus first
    document.querySelectorAll('.user-action-menu.show').forEach(m => m.classList.remove('show'));
    if (!isOpen) menu.classList.add('show');
}

// Close dropdowns when clicking outside
document.addEventListener('click', () => {
    document.querySelectorAll('.user-action-menu.show').forEach(m => m.classList.remove('show'));
});

// ── User Edit View State ──────────────────────────────────────────
let currentEditUser = null; // stores the full user object being edited

// Opens the full-page user edit view, pre-populating all fields
async function openUserEdit(userId) {
    // Close any open dropdowns first
    document.querySelectorAll('.user-action-menu.show').forEach(m => m.classList.remove('show'));

    try {
        // Fetch up-to-date user list and find the target user
        const res = await fetch(`${API}/users`, { headers: authHeaders() });
        if (!res.ok) throw new Error('Could not load user data');
        const users = await res.json();
        const u = users.find(x => x.id === userId);
        if (!u) { showToast('User not found', 'error'); return; }
        currentEditUser = u;

        // Populate header
        document.getElementById('ue-header-name').textContent = u.full_name || u.username;
        document.getElementById('ue-header-sub').textContent =
            `@${u.username} · ${u.role.charAt(0).toUpperCase() + u.role.slice(1)}`;

        // Populate User Information fields
        document.getElementById('ue-fullname').value  = u.full_name  || '';
        document.getElementById('ue-email').value     = u.email      || '';
        document.getElementById('ue-username').value  = u.username   || '';
        document.getElementById('ue-role').value      = u.role       || 'viewer';

        // Status badge
        const badge = document.getElementById('ue-status-badge');
        const isActive = u.is_active !== false;
        badge.textContent = isActive ? '● Active' : '● Inactive';
        badge.className = isActive ? 'ue-status-badge ue-status-active' : 'ue-status-badge ue-status-inactive';

        // Deactivate/Reactivate button label
        const deactivateLabel = document.getElementById('ue-deactivate-label');
        const deactivateBtn   = document.getElementById('ue-deactivate-btn');
        if (isActive) {
            deactivateLabel.textContent = 'Deactivate User';
            deactivateBtn.textContent   = 'Deactivate';
            deactivateBtn.className     = 'btn-ue-deactivate';
        } else {
            deactivateLabel.textContent = 'Reactivate User';
            deactivateBtn.textContent   = 'Reactivate';
            deactivateBtn.className     = 'btn-ue-reactivate';
        }

        // Clear password fields & all messages
        document.getElementById('ue-new-password').value     = '';
        document.getElementById('ue-confirm-password').value = '';
        ['ue-msg-info','ue-msg-pw','ue-msg-airport'].forEach(id => {
            const el = document.getElementById(id);
            el.style.display = 'none'; el.textContent = '';
            el.className = 'msg-box';
        });

        // Load airports into the select + set current airport display
        await loadUEAirports(u.airport_id);

        // Navigate to the edit page
        showPage('user-edit');
    } catch (err) {
        showToast(err.message, 'error');
    }
}

// Loads airports into the reassign-airport dropdown and sets the current-airport read-only field
async function loadUEAirports(currentAirportId) {
    const sel = document.getElementById('ue-airport-select');
    const currentDisplay = document.getElementById('ue-current-airport');
    sel.innerHTML = '<option value="">— All Airports (Admin) —</option>';
    try {
        const res = await fetch(`${API}/airports`, { headers: authHeaders() });
        if (!res.ok) return;
        const airports = await res.json();
        airports.forEach(a => {
            const opt = document.createElement('option');
            opt.value = a.id;
            opt.textContent = `${a.name} (${a.code})`;
            if (a.id === currentAirportId) opt.selected = true;
            sel.appendChild(opt);
        });
        // Set read-only display
        if (currentAirportId) {
            const found = airports.find(a => a.id === currentAirportId);
            currentDisplay.value = found ? `${found.name} (${found.code})` : `Airport #${currentAirportId}`;
        } else {
            currentDisplay.value = 'All Airports (Admin)';
        }
    } catch (e) { console.error(e); }
}

// Helper: show a message inside one of the edit-view cards
function showUEMsg(id, text, type) {
    const el = document.getElementById(id);
    el.textContent = text;
    el.className = `msg-box msg-${type}`;
    el.style.display = 'block';
    setTimeout(() => { el.style.display = 'none'; }, 4000);
}

// Saves full-name, email, and role changes
async function saveUserInfo() {
    if (!currentEditUser) return;
    const payload = {
        full_name: document.getElementById('ue-fullname').value.trim(),
        email:     document.getElementById('ue-email').value.trim(),
        role:      document.getElementById('ue-role').value,
    };
    if (!payload.full_name || !payload.email) {
        showUEMsg('ue-msg-info', 'Name and email are required.', 'error'); return;
    }
    try {
        const res = await fetch(`${API}/auth/users/${currentEditUser.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify(payload),
        });
        if (!res.ok) {
            const e = await res.json().catch(() => ({}));
            throw new Error(parseApiError(e, 'Update failed'));
        }
        currentEditUser = { ...currentEditUser, ...payload };
        document.getElementById('ue-header-name').textContent = payload.full_name;
        document.getElementById('ue-header-sub').textContent =
            `@${currentEditUser.username} · ${payload.role.charAt(0).toUpperCase() + payload.role.slice(1)}`;
        showUEMsg('ue-msg-info', '✓ Profile updated successfully.', 'success');
        showToast('User info updated', 'success');
    } catch (err) { showUEMsg('ue-msg-info', err.message, 'error'); }
}

// Changes the user's password (manual entry)
async function changeUserPassword() {
    if (!currentEditUser) return;
    const pw  = document.getElementById('ue-new-password').value;
    const cfm = document.getElementById('ue-confirm-password').value;
    if (!pw) { showUEMsg('ue-msg-pw', 'Please enter a new password.', 'error'); return; }
    if (pw !== cfm) { showUEMsg('ue-msg-pw', 'Passwords do not match.', 'error'); return; }
    const pwError = validateStrongPassword(pw, currentEditUser.username, currentEditUser.email, currentEditUser.full_name);
    if (pwError) { showUEMsg('ue-msg-pw', pwError, 'error'); return; }
    try {
        const res = await fetch(`${API}/auth/users/${currentEditUser.id}/reset-password`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify({ password: pw }),  // ← backend requires { "password": "..." }
        });
        if (!res.ok) {
            const e = await res.json().catch(() => ({}));
            throw new Error(parseApiError(e, 'Password change failed'));
        }
        document.getElementById('ue-new-password').value     = '';
        document.getElementById('ue-confirm-password').value = '';
        showUEMsg('ue-msg-pw', '✓ Password changed successfully.', 'success');
        showToast('Password updated', 'success');
    } catch (err) { showUEMsg('ue-msg-pw', err.message, 'error'); }
}

// Sends a system-generated temporary password to the user's registered email.
// Calls POST /auth/users/{id}/send-reset-email (admin-only, no request body).
// The backend generates a random 12-char password, bcrypt-hashes and stores it,
// then emails the new credentials. The admin never sees the generated password.
async function resetPasswordFromEdit() {
    if (!currentEditUser) return;
    const email = currentEditUser.email || currentEditUser.username;
    if (!confirm(
        `Send a system-generated temporary password to ${currentEditUser.username}?\n\n` +
        `A new random password will be emailed to their registered address.\n` +
        `Their current password will be replaced immediately.`
    )) return;

    try {
        const res = await fetch(
            `${API}/auth/users/${currentEditUser.id}/send-reset-email`,
            {
                method:  'POST',
                headers: { 'Content-Type': 'application/json', ...authHeaders() },
            }
        );

        if (!res.ok) {
            const e = await res.json().catch(() => ({}));
            throw new Error(parseApiError(e, 'Reset email failed'));
        }

        // Surface the backend message — it includes the target email address
        const data = await res.json().catch(() => ({}));
        const msg  = data.message || 'Reset password email sent successfully.';
        showUEMsg('ue-msg-pw', `\u2713 ${msg}`, 'success');
        showToast('Reset email sent', 'success');

    } catch (err) {
        showUEMsg('ue-msg-pw', err.message, 'error');
    }
}


// Reassigns the user to a different airport
async function changeUserAirport() {
    if (!currentEditUser) return;
    const airportIdRaw = document.getElementById('ue-airport-select').value;
    const airportId = airportIdRaw ? parseInt(airportIdRaw) : null;
    try {
        const res = await fetch(`${API}/auth/users/${currentEditUser.id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify({ airport_id: airportId }),
        });
        if (!res.ok) {
            const e = await res.json().catch(() => ({}));
            throw new Error(parseApiError(e, 'Airport update failed'));
        }
        currentEditUser.airport_id = airportId;
        const sel = document.getElementById('ue-airport-select');
        const selectedText = sel.options[sel.selectedIndex].text;
        document.getElementById('ue-current-airport').value = selectedText;
        showUEMsg('ue-msg-airport', '✓ Airport updated successfully.', 'success');
        showToast('Airport assignment updated', 'success');
    } catch (err) { showUEMsg('ue-msg-airport', err.message, 'error'); }
}

// Toggles between deactivate and reactivate
async function toggleUserDeactivate() {
    if (!currentEditUser) return;
    const isActive = currentEditUser.is_active !== false;
    const action   = isActive ? 'Deactivate' : 'Reactivate';
    if (!confirm(`${action} account for "${currentEditUser.username}"?`)) return;
    try {
        // Backend uses /deactivate and /activate (not /reactivate)
        const endpoint = isActive
            ? `${API}/auth/users/${currentEditUser.id}/deactivate`
            : `${API}/auth/users/${currentEditUser.id}/activate`;
        const res = await fetch(endpoint, { method: 'PUT', headers: authHeaders() });
        if (!res.ok) {
            const e = await res.json().catch(() => ({}));
            throw new Error(parseApiError(e, `${action} failed`));
        }
        currentEditUser.is_active = !isActive;
        const newActive = currentEditUser.is_active;
        const badge = document.getElementById('ue-status-badge');
        badge.textContent = newActive ? '● Active' : '● Inactive';
        badge.className   = newActive ? 'ue-status-badge ue-status-active' : 'ue-status-badge ue-status-inactive';
        const btn = document.getElementById('ue-deactivate-btn');
        const lbl = document.getElementById('ue-deactivate-label');
        if (newActive) {
            lbl.textContent = 'Deactivate User';
            btn.textContent = 'Deactivate';
            btn.className   = 'btn-ue-deactivate';
        } else {
            lbl.textContent = 'Reactivate User';
            btn.textContent = 'Reactivate';
            btn.className   = 'btn-ue-reactivate';
        }
        showToast(`${currentEditUser.username} ${newActive ? 'reactivated' : 'deactivated'}`, 'success');
    } catch (err) { showToast(err.message, 'error'); }
}

// Deletes the user then returns to the users list
async function deleteUserFromEdit() {
    if (!currentEditUser) return;
    if (!confirm(`Permanently delete user "${currentEditUser.username}"? This cannot be undone.`)) return;
    if (!confirm(`Are you absolutely sure? All data for "${currentEditUser.username}" will be lost.`)) return;
    try {
        const res = await fetch(`${API}/auth/users/${currentEditUser.id}`, {
            method: 'DELETE',
            headers: authHeaders(),
        });
        if (!res.ok) {
            const e = await res.json().catch(() => ({}));
            throw new Error(parseApiError(e, 'Delete failed'));
        }
        showToast(`${currentEditUser.username} deleted`, 'success');
        currentEditUser = null;
        showPage('register');
    } catch (err) { showToast(err.message, 'error'); }
}

// ── Admin Edit (original prompt-based flow — used for admin-role accounts only) ──
// Mirrors the original editUser() that existed before the full-page edit view was added.
async function editUser(userId, username) {
    const newName = prompt(`Edit admin "${username}"\nNew full name (leave blank to skip):`);
    // If the user pressed Cancel on the first prompt, abort entirely
    if (newName === null) return;

    const payload = {};
    if (newName.trim()) payload.full_name = newName.trim();
    if (!Object.keys(payload).length) return; // nothing to update

    try {
        const res = await fetch(`${API}/auth/users/${userId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify(payload),
        });
        if (!res.ok) {
            const e = await res.json().catch(() => ({}));
            throw new Error(parseApiError(e, 'Update failed'));
        }
        showToast('Admin user updated successfully', 'success');
        loadUsers();
    } catch (err) { showToast(err.message, 'error'); }
}

// ── Admin Reset Password ──
// The backend endpoint PUT /auth/users/{id}/reset-password expects a JSON body:
//   { "password": "<new_plaintext_password>" }
// This function prompts the admin for the new password, validates it,
// then posts it to the backend for bcrypt hashing and storage.
async function resetPassword(userId, username) {
    // Step 1: confirm intent
    if (!confirm(`Reset password for "${username}"?\n\nYou will be prompted to enter a new password.`)) return;

    // Step 2: collect new password
    const newPw = prompt(`Enter the NEW password for "${username}":`);
    if (newPw === null) return;            // user pressed Cancel
    if (!newPw.trim()) {
        showToast('Password cannot be empty.', 'error');
        return;
    }
    if (newPw.length < 6) {
        showToast('Password must be at least 6 characters.', 'error');
        return;
    }

    // Step 3: confirm new password
    const confirmPw = prompt(`Confirm new password for "${username}":`);
    if (confirmPw === null) return;        // cancelled
    if (newPw !== confirmPw) {
        showToast('Passwords do not match. Reset cancelled.', 'error');
        return;
    }

    // Step 4: call backend with the required { "password": "..." } body
    try {
        const res = await fetch(`${API}/auth/users/${userId}/reset-password`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify({ password: newPw }),  // ← required by the backend
        });
        if (!res.ok) {
            const e = await res.json().catch(() => ({}));
            throw new Error(parseApiError(e, 'Password reset failed'));
        }
        showToast(`✓ Password reset for "${username}" successfully`, 'success');
    } catch (err) { showToast(err.message, 'error'); }
}

// ── Flights ───────────────────────────────────────────────────────
function setupFlightPage() {
    document.getElementById('bc-airport').textContent = selectedAirport.city;
    document.getElementById('flight-page-title').innerHTML =
        `${selectedAirport.name} <span style="color:var(--cyan);font-size:18px">(${selectedAirport.code})</span>`;
    document.getElementById('flight-page-sub').textContent =
        `${selectedAirport.city} — Flight Board`;
    document.getElementById('f-destination').value =
        `${selectedAirport.city} (${selectedAirport.code})`;

    document.getElementById('btn-add-flight').classList.toggle('hidden', role === 'viewer');
    document.getElementById('btn-sync-live').classList.toggle('hidden', role !== 'admin');
    document.getElementById('actions-th').style.display = role !== 'admin' ? 'none' : '';

    // Only reset to arrival on FIRST load (when no activeCategory is set yet)
    if (!activeCategory || activeCategory === 'info') {
        activeCategory = 'arrival';
    }
    activeTerminal = 'ALL';
    activeAirline = 'ALL';
    activeStatusFilter = 'ALL'; // reset stat-card filter on page setup
    document.querySelectorAll('.category-card').forEach(c => c.classList.remove('active'));
    const activeCatEl = document.querySelector(`[data-type="${activeCategory}"]`);
    if (activeCatEl) activeCatEl.classList.add('active');
    document.getElementById('flight-board-section').classList.remove('hidden');
    document.getElementById('airline-info-section').classList.add('hidden');
    document.querySelectorAll('.tab-btn').forEach((b, i) => b.classList.toggle('active', i === 0));
    document.getElementById('airline-filter').value = 'ALL';
    // Clear any active stat card highlight
    document.querySelectorAll('.stat-card').forEach(c => c.classList.remove('active-stat'));
}

function setCategory(type, el) {
    activeCategory = type;
    // Track last real flight tab (not info)
    if (type === 'arrival' || type === 'departure') {
        lastFlightCategory = type;
    }
    document.querySelectorAll('.category-card').forEach(c => c.classList.remove('active'));
    el.classList.add('active');
    if (type === 'info') {
        document.getElementById('flight-board-section').classList.add('hidden');
        document.getElementById('airline-info-section').classList.remove('hidden');
    } else {
        document.getElementById('flight-board-section').classList.remove('hidden');
        document.getElementById('airline-info-section').classList.add('hidden');
        renderBoard();
    }
}

function setTerminal(term, btn) {
    activeTerminal = term;
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    renderBoard();
}

async function fetchFlights() {
    if (!selectedAirport || !token) return;
    try {
        const res = await fetch(`${API}/airports/${selectedAirport.id}/flights`, { headers: authHeaders() });
        if (res.status === 401) { handleLogout(); return; }
        allFlights = await res.json();
        updateAllAirlineCards();
        if (activeCategory !== 'info') {
            renderBoard();
            // loadBHSLog(); // Temporarily disabled to prevent 422 spam
        }
    } catch (err) {
        console.error(err);
    }
}

function updateBreadcrumb() {
    const bc = document.getElementById('airline-breadcrumb');
    if (bc) {
        if (selectedAirline) {
            bc.innerHTML = `<span onclick="clearAirlineFilter()" style="cursor:pointer;color:var(--primary);text-decoration:underline;font-weight:600;">All Airlines</span> &nbsp;&gt;&nbsp; <span style="color:var(--text1);font-weight:bold;">${selectedAirline}</span>`;
        } else {
            bc.innerHTML = `<span style="color:var(--text2);">All Airlines</span>`;
        }
    }
}

function selectAirline(event, airline) {
    selectedAirline = airline;
    document.querySelectorAll('.airline-info-card').forEach(c => {
        c.classList.remove('active');
    });
    if (event) event.currentTarget.classList.add('active');

    updateBreadcrumb();

    // If on the info tab, switch to flight board using LAST real tab (not forced arrival)
    if (activeCategory === 'info') {
        const targetType = lastFlightCategory; // ✅ restore last arrival/departure tab
        activeCategory = targetType;
        document.querySelectorAll('.category-card').forEach(c => c.classList.remove('active'));
        const targetEl = document.querySelector(`[data-type="${targetType}"]`);
        if (targetEl) targetEl.classList.add('active');
        document.getElementById('flight-board-section').classList.remove('hidden');
        document.getElementById('airline-info-section').classList.add('hidden');
    }
    // Always just re-render — do NOT force tab change if already on departure/arrival
    renderBoard();
}

function clearAirlineFilter() {
    selectedAirline = null;
    document.querySelectorAll('.airline-info-card').forEach(c => {
        c.classList.remove('active');
    });
    updateBreadcrumb();
    renderBoard();
}

function updateAllAirlineCards() {
    const airlineStats = {};

    allFlights.forEach(f => {
        const airline = f.airline_name;
        if (!airlineStats[airline]) {
            airlineStats[airline] = { total: 0, delayed: 0, boarding: 0 };
        }

        airlineStats[airline].total++;
        if (f.status === "Delayed") airlineStats[airline].delayed++;
        if (f.status === "Boarding") airlineStats[airline].boarding++;
    });

    function updateAirlineCard(id, name) {
        const stats = airlineStats[name] || { total: 0, delayed: 0, boarding: 0 };
        document.getElementById(id).innerText = `${stats.total} flights • ${stats.delayed} delayed • ${stats.boarding} boarding`;
    }

    updateAirlineCard("indigo-stats", "IndiGo");
    updateAirlineCard("airindia-stats", "Air India");
    updateAirlineCard("emirates-stats", "Emirates");
    updateAirlineCard("vistara-stats", "Vistara");
    updateAirlineCard("akasa-stats", "Akasa Air");
}

// ── Status-card filter ────────────────────────────────────────────
// Called when a stat card is clicked. Toggles the status filter and
// re-renders the board without re-fetching from the server.
function filterByStatus(status) {
    // Toggle OFF if the same card is clicked again → show all
    activeStatusFilter = (activeStatusFilter === status) ? 'ALL' : status;

    // Update active-stat class on all cards
    document.querySelectorAll('.stat-card').forEach(card => {
        const cardStatus = card.getAttribute('data-status');
        if (activeStatusFilter !== 'ALL' && cardStatus === activeStatusFilter) {
            card.classList.add('active-stat');
        } else {
            card.classList.remove('active-stat');
        }
    });

    renderBoard();
}

// ── Route Formatter ──────────────────────────────────────────────
// Converts strings like "Indira Gandhi International (DEL)" or 
// "Chhatrapati Shivaji Intl (BOM)" into "Delhi (DEL)" and "Mumbai (BOM)".
const IATA_CITY_MAP = {
    'DEL': 'Delhi',
    'BOM': 'Mumbai',
    'BLR': 'Bengaluru',
    'HYD': 'Hyderabad',
    'MAA': 'Chennai',
    'CCU': 'Kolkata',
    'PNQ': 'Pune',
    'AMD': 'Ahmedabad',
    'JAI': 'Jaipur',
    'LKO': 'Lucknow',
    'GOI': 'Goa',
    'COK': 'Kochi',
    'DXB': 'Dubai',
    'LHR': 'London',
    'JFK': 'New York',
    'SIN': 'Singapore',
    'NRT': 'Tokyo',
    'CDG': 'Paris',
    'FRA': 'Frankfurt',
    'AMS': 'Amsterdam',
    'DOH': 'Doha',
    'KUL': 'Kuala Lumpur',
    'BKK': 'Bangkok',
    'SYD': 'Sydney',
    'LAX': 'Los Angeles',
    'YYZ': 'Toronto'
};

function formatRoute(origin, destination) {
    const getCleanName = (str) => {
        const iataMatch = str.match(/\(([A-Z]{3})\)/);
        if (!iataMatch) return str;
        const iata = iataMatch[1];
        const city = IATA_CITY_MAP[iata] || str.split('(')[0].trim();
        return `${city} (${iata})`;
    };
    return `${getCleanName(origin)} &rarr; ${getCleanName(destination)}`;
}

/**
 * Deterministic carousel assignment helper for the frontend.
 * Ensures every flight has a visual assignment even if the backend
 * is still processing the event.
 */
function getCarousel(flightNumber, terminal) {
    if (!terminal) return "TBD";
    const mapping = {
        "T1": ["C1", "C2", "C3", "C4"],
        "T2": ["C5", "C6", "C7", "C8"],
        "T3": ["C9", "C10", "C11", "C12"]
    };
    const options = mapping[terminal] || ["C1", "C2"];
    
    // Simple hash for string
    let hash = 0;
    for (let i = 0; i < flightNumber.length; i++) {
        hash = ((hash << 5) - hash) + flightNumber.charCodeAt(i);
        hash |= 0;
    }
    const index = Math.abs(hash) % options.length;
    return options[index];
}

function carouselCell(flight) {
    if (flight.status !== 'Arrived') {
        return `<span class="carousel-na">—</span>`;
    }

    const carousel =
        flight.carousel_number ||
        getCarousel(flight.flight_number, flight.terminal_number);

    return `<span class="carousel-badge">${carousel}</span>`;
}

function closeEditModal() {
    const modal = document.getElementById("edit-modal");
    if (modal) {
        modal.classList.add("hidden");
        modal.style.display = "none";
    }
}

// Removed separate carousel modal handlers

async function loadBHSLog() {
    // Fail silently if bhs-log-body is missing or backend returns error
    const body = document.getElementById("bhs-log-body");
    if (!body) return;

    try {
        const res = await fetch(`${API}/flights/carousel-log`, {
            headers: authHeaders()
        });
        if (!res.ok) return; // Silent return on 422, 404, 500 etc.
        
        const logs = await res.json();
        body.innerHTML = "";
        logs.forEach(log => {
            const statusClass = log.event_type === 'CAROUSEL_ASSIGNED' ? 'bhs-assigned' : 'bhs-changed';
            body.innerHTML += `
                <tr>
                    <td><span class="bhs-flight">${log.flight_number}</span></td>
                    <td><span class="bhs-carousel">${log.new_carousel}</span></td>
                    <td><span class="bhs-status ${statusClass}">${log.event_type.replace('_', ' ')}</span></td>
                    <td><span class="bhs-time">${log.changed_at}</span></td>
                </tr>
            `;
        });
    } catch (err) {
        // Silent catch
    }
}

function renderBoard() {
    // 1. Filter by category (arrival / departure)
    let filtered = allFlights.filter(f => f.flight_type === activeCategory);

    // 2. Filter by terminal
    if (activeTerminal !== 'ALL') filtered = filtered.filter(f => f.terminal_number === activeTerminal);

    // 3. Filter by dropdown airline
    if (activeAirline !== 'ALL') filtered = filtered.filter(f => f.airline_code === activeAirline);

    // 4. Filter by clicked airline info card
    if (selectedAirline) filtered = filtered.filter(f => f.airline_name === selectedAirline);

    // 5. Sort flights by departure time chronologically
    filtered.sort((a, b) => a.departure_time.localeCompare(b.departure_time));

    // Update stat card counts BEFORE applying the status filter so totals are never broken.
    // Counts always reflect all flights for the current category/terminal/airline selection.
    document.getElementById('stat-total').textContent = filtered.length;
    document.getElementById('stat-arrived').textContent = filtered.filter(f => f.status.toLowerCase() === 'arrived').length;
    document.getElementById('stat-boarding').textContent = filtered.filter(f => f.status.toLowerCase() === 'boarding').length;
    document.getElementById('stat-scheduled').textContent = filtered.filter(f => f.status.toLowerCase() === 'scheduled').length;
    document.getElementById('stat-delayed').textContent = filtered.filter(f => f.status.toLowerCase() === 'delayed').length;

    // 6. Apply status card filter (case-insensitive) — AFTER counting totals
    if (activeStatusFilter !== 'ALL') {
        const target = activeStatusFilter.toLowerCase();
        filtered = filtered.filter(f => f.status.toLowerCase() === target);
    }

    const tbody = document.getElementById('flights-tbody');
    const empty = document.getElementById('empty-state');
    const wrapper = document.getElementById('table-wrapper');

    if (filtered.length === 0) {
        // Customise empty-state message when a status filter is active
        const emptyIcon = empty.querySelector('.empty-icon');
        const emptyTitle = empty.querySelector('h3');
        const emptyDesc = empty.querySelector('p');
        if (activeStatusFilter !== 'ALL') {
            if (emptyIcon) emptyIcon.textContent = '🔍';
            if (emptyTitle) emptyTitle.textContent = 'No flights found';
            if (emptyDesc) emptyDesc.textContent = `No flights found for status "${activeStatusFilter}". Try a different filter.`;
        } else {
            if (emptyIcon) emptyIcon.textContent = '🛬';
            if (emptyTitle) emptyTitle.textContent = 'No flights found';
            if (emptyDesc) emptyDesc.textContent = 'No flights match the current filters. Try syncing live data.';
        }
        empty.classList.remove('hidden');
        wrapper.style.display = 'none';
    } else {
        empty.classList.add('hidden');
        wrapper.style.display = 'block';
    }

    tbody.innerHTML = '';
    filtered.forEach(f => {
        const tr = document.createElement('tr');
        let actions = '';

        if (role === 'admin' || role === 'staff') {
            if (role === 'admin') {
                actions = `
                    <td class="cell-actions">
                        <div class="action-container">
                            <button class="action-btn btn-edit" onclick="editFlight(${f.id})">Edit</button>
                            <button class="action-btn btn-delete" onclick="deleteFlight(${f.id})">Delete</button>
                        </div>
                    </td>`;
            } else if (role === 'staff') {
                actions = `
                    <td class="cell-actions">
                        <div class="action-container">
                            <button class="action-btn btn-edit" onclick="editFlight(${f.id})">Edit</button>
                        </div>
                    </td>`;
            }
        }

        tr.innerHTML = `
  <td class="cell-flight">${f.flight_number}</td>
  <td class="cell-airline-info"><div class="cell-airline"><span class="airline-badge badge-${f.airline_code}">${f.airline_code}</span>${f.airline_name}</div></td>
  <td class="cell-route">${formatRoute(f.origin, f.destination)}</td>
  <td class="cell-time">${f.departure_time}</td>
  <td class="cell-time">${f.arrival_time}</td>
  <td class="cell-gate">${f.gate_number}</td>
  <td class="cell-terminal-info"><span class="terminal-badge terminal-${f.terminal_number}">${f.terminal_number}</span></td>
  <td class="cell-carousel">${carouselCell(f)}</td>
  <td class="cell-status">${renderStatusCell(f)}</td>
  ${actions}`;
        tbody.appendChild(tr);
    });
}

function renderStatusCell(f) {
    return `<span class="status-badge status-${f.status.replace(/\s+/g, '-')}">${f.status}</span>`;
}

function toggleForm() {
    document.getElementById('add-flight-form').classList.toggle('hidden');
}

async function submitFlight() {
    const payload = {
        flight_number: document.getElementById('f-number').value.trim(),
        airline_code: document.getElementById('f-airline').value,
        // Staff: airport_id is ignored by server (auto-assigned from user profile)
        // Admin: airport_id is required — use selectedAirport
        airport_id: role === 'admin' ? selectedAirport.id : null,
        origin: document.getElementById('f-origin').value.trim(),
        destination: document.getElementById('f-destination').value.trim(),
        departure_time: document.getElementById('f-departure').value,
        arrival_time: document.getElementById('f-arrival').value,
        gate_number: document.getElementById('f-gate').value.trim(),
        terminal_number: document.getElementById('f-terminal').value,
        status: document.getElementById('f-status').value,
        flight_type: activeCategory,
    };
    try {
        const res = await fetch(`${API}/flights`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (res.status === 202) {
            // Async — queued via RabbitMQ
            showToast(`Flight ${payload.flight_number} queued! Processing...`, 'success');
            document.getElementById('f-number').value = '';
            document.getElementById('f-origin').value = '';
            toggleForm();
            // Refresh after short delay to allow worker to process
            setTimeout(fetchFlights, 3000);
        } else if (!res.ok) {
            throw new Error(data.detail || 'Failed to queue flight');
        }
    } catch (err) { showToast(err.message, 'error'); }
}

async function deleteFlight(id) {
    if (!confirm('Delete this flight?')) return;
    try {
        const res = await fetch(`${API}/flights/${id}`, { method: 'DELETE', headers: authHeaders() });
        if (!res.ok) throw new Error('Failed to delete');
        showToast('Flight deleted', 'success');
        await fetchFlights();
    } catch (err) { showToast(err.message, 'error'); }
}

async function editFlight(id) {
    const flight = allFlights.find(f => f.id === id);
    if (!flight) return;

    const modal = document.getElementById('edit-modal');
    const body = document.getElementById('edit-modal-body');
    const saveBtn = document.getElementById('edit-modal-save');

    if (!modal || !body || !saveBtn) return;

    const currentCarousel = flight.carousel_number || getCarousel(flight.flight_number, flight.terminal_number);

    body.innerHTML = `
        <div class="form-group">
            <label>Flight Status</label>
            <select id="edit-status">
                <option value="Scheduled" ${flight.status === 'Scheduled' ? 'selected' : ''}>Scheduled</option>
                <option value="Boarding" ${flight.status === 'Boarding' ? 'selected' : ''}>Boarding</option>
                <option value="Departed" ${flight.status === 'Departed' ? 'selected' : ''}>Departed</option>
                <option value="Arrived" ${flight.status === 'Arrived' ? 'selected' : ''}>Arrived</option>
                <option value="Delayed" ${flight.status === 'Delayed' ? 'selected' : ''}>Delayed</option>
                <option value="Cancelled" ${flight.status === 'Cancelled' ? 'selected' : ''}>Cancelled</option>
            </select>
        </div>

        <div id="delay-fields" class="${flight.status === 'Delayed' ? '' : 'hidden'}" style="margin-top:16px; border-top:1px solid #eee; padding-top:16px">
            <div class="form-group">
                <label>Delay Minutes</label>
                <input type="number" id="edit-delay-minutes" value="${flight.delay_minutes || 0}" min="0">
            </div>
            <div class="form-group">
                <label>Delay Reason</label>
                <select id="edit-delay-reason">
                    <option value="Weather" ${flight.delay_reason === 'Weather' ? 'selected' : ''}>Weather</option>
                    <option value="Technical" ${flight.delay_reason === 'Technical' ? 'selected' : ''}>Technical</option>
                    <option value="ATC" ${flight.delay_reason === 'ATC' ? 'selected' : ''}>ATC</option>
                    <option value="Crew" ${flight.delay_reason === 'Crew' ? 'selected' : ''}>Crew</option>
                    <option value="Security" ${flight.delay_reason === 'Security' ? 'selected' : ''}>Security</option>
                    <option value="Late Arrival" ${flight.delay_reason === 'Late Arrival' ? 'selected' : ''}>Late Arrival</option>
                    <option value="Operational" ${flight.delay_reason === 'Operational' ? 'selected' : ''}>Operational</option>
                    <option value="Other" ${flight.delay_reason === 'Other' ? 'selected' : ''}>Other</option>
                </select>
            </div>
        </div>

        <div class="form-group">
            <label>Gate Number</label>
            <input type="text" id="edit-gate" value="${flight.gate_number}">
        </div>
        ${flight.status === 'Arrived' ? `
        <div class="form-group" style="margin-top:16px; border-top:1px solid #eee; padding-top:16px">
            <label>Carousel Number</label>
            <input type="text" id="edit-carousel" value="${currentCarousel}">
        </div>
        <div class="form-group">
            <label>Change Reason (Optional)</label>
            <input type="text" id="edit-reason" placeholder="e.g. Mechanical fault on C3">
        </div>
        ` : ''}
    `;

    saveBtn.onclick = () => saveFlightChanges(id, flight);
    
    // Add change listener for status to toggle delay fields
    const statusSelect = document.getElementById('edit-status');
    if (statusSelect) {
        statusSelect.onchange = () => {
            const delayFields = document.getElementById('delay-fields');
            if (statusSelect.value === 'Delayed') {
                delayFields.classList.remove('hidden');
            } else {
                delayFields.classList.add('hidden');
            }
        };
    }

    modal.classList.remove('hidden');
    modal.style.display = 'flex'; // Support cpw-overlay flex layout
}

async function saveFlightChanges(id, originalFlight) {
    const status = document.getElementById('edit-status').value;
    const gate = document.getElementById('edit-gate').value.trim();
    
    const payload = { status, gate_number: gate };
    if (status === 'Delayed') {
        payload.delay_minutes = parseInt(document.getElementById('edit-delay-minutes').value) || 0;
        payload.delay_reason = document.getElementById('edit-delay-reason').value;
    } else {
        // Clear delay info if flight is no longer delayed
        payload.delay_minutes = 0;
        payload.delay_reason = null;
    }

    try {
        // Step 1: Update main flight data
        const res = await fetch(`${API}/flights/${id}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json", ...authHeaders() },
            body: JSON.stringify(payload)
        });
        if (!res.ok) throw new Error("Update failed");

        // Step 2: Update carousel if changed and flight is Arrived
        if (originalFlight.status === 'Arrived') {
            const carousel = document.getElementById('edit-carousel').value.trim();
            const reason = document.getElementById('edit-reason').value.trim() || "Manual override via Edit workflow";
            
            const currentVal = originalFlight.carousel_number || getCarousel(originalFlight.flight_number, originalFlight.terminal_number);
            
            if (carousel !== currentVal) {
                const cRes = await fetch(`${API}/flights/${id}/carousel`, {
                    method: "PUT",
                    headers: { "Content-Type": "application/json", ...authHeaders() },
                    body: JSON.stringify({ carousel_number: carousel, reason })
                });
                if (!cRes.ok) showToast("Flight updated, but carousel change failed", "warning");
            }
        }

        showToast("Flight updated successfully", "success");
        closeEditModal();
        fetchFlights();
        loadBHSLog();
    } catch (err) {
        showToast(err.message, "error");
    }
}

async function syncLiveFlights() {
    const btn = document.getElementById('btn-sync-live');
    if (!btn) return;

    // ── Loading state ──────────────────────────────────────────
    btn.disabled = true;
    const originalText = btn.textContent;
    btn.innerHTML = '<span class="btn-spinner"></span> Syncing...';

    try {
        const res = await fetch(`${API}/flights/sync-live`, {
            method: 'POST',
            headers: authHeaders(),
        });

        if (res.ok) {
            showToast('✅ Live flight sync completed successfully', 'success');
            setTimeout(fetchFlights, 4000);   // allow worker a moment to process
        } else {
            const err = await res.json().catch(() => ({}));
            showToast(err.detail || '❌ Sync failed — check backend logs', 'error');
        }
    } catch (err) {
        showToast('❌ Cannot reach backend — ensure uvicorn is running on port 8000', 'error');
    } finally {
        // ── Restore button regardless of outcome ───────────────
        btn.disabled = false;
        btn.innerHTML = originalText;
    }
}

// ── Helpers ───────────────────────────────────────────────────────
function authHeaders() {
    return token ? { 'Authorization': `Bearer ${token}` } : {};
}

/**
 * parseApiError(e)
 * Safely extracts a readable error string from any FastAPI/HTTP response object.
 * FastAPI returns `detail` as:
 *   - a plain string  → "User not found"
 *   - an array        → Pydantic validation errors [{loc,msg,type}, ...]
 *   - an object       → rare custom shapes
 * Falls back to `e.message` (JS Error), then a provided fallback string.
 */
function parseApiError(e, fallback = 'Request failed') {
    // e is the parsed JSON body from the API response
    if (!e) return fallback;

    const detail = e.detail;

    if (!detail) {
        // Try common alternative keys
        if (e.message && typeof e.message === 'string') return e.message;
        return fallback;
    }

    if (typeof detail === 'string') return detail;   // plain string — most common

    if (Array.isArray(detail)) {
        // Pydantic validation error array — each item has {loc, msg, type}
        return detail.map(d => {
            const field = Array.isArray(d.loc) ? d.loc.slice(-1)[0] : '';
            return field ? `${field}: ${d.msg}` : d.msg;
        }).join('; ');
    }

    // Unexpected object shape — stringify gracefully
    try { return JSON.stringify(detail); } catch { return fallback; }
}

function showToast(msg, type) {
    const existing = document.querySelector('.toast');
    if (existing) existing.remove();
    const t = document.createElement('div');
    t.className = `toast toast-${type}`;
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3200);
}

// ── App Init ──────────────────────────────────────────────────────
(function init() {
    token = localStorage.getItem('token');
    role = localStorage.getItem('role');
    fullName = localStorage.getItem('fullName');
    const stored = localStorage.getItem('selectedAirport');
    if (stored) {
        try { selectedAirport = JSON.parse(stored); } catch (e) { }
    }

    // Check if token is expired
    if (token) {
        try {
            const payload = JSON.parse(atob(token.split('.')[1]));
            const isExpired = payload.exp * 1000 < Date.now();
            if (isExpired) {
                console.log('[Auth] Token expired — clearing session');
                localStorage.clear();
                token = role = fullName = selectedAirport = null;
            }
        } catch (e) {
            // Invalid token — clear session
            localStorage.clear();
            token = role = fullName = selectedAirport = null;
        }
    }

    if (token) {
        setupNavbar();
        if (role === 'admin') {
            // Admin sees airport selection
            showPage('airports');
        } else if ((role === 'staff' || role === 'viewer') && selectedAirport) {
            // Staff/Viewer go directly to their airport's flights
            showPage('flights');
        } else {
            // Fallback — airport selection
            showPage('airports');
        }
    } else {
        showPage('landing');
    }
})();

// ── Analytics Dashboard ───────────────────────────────────────────
// Chart instances are stored at module scope so we can destroy/recreate
// them on each refresh without creating memory leaks in Chart.js.
let statusChartInstance  = null;
let airlineChartInstance = null;
let airportChartInstance = null;

async function loadAnalytics() {
    // Show a loading placeholder in the KPI grid on the first render
    const kpiGrid = document.getElementById('analytics-kpis');
    if (kpiGrid && !kpiGrid.innerHTML.trim()) {
        kpiGrid.innerHTML = '<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: var(--text3);">Loading operational data…</div>';
    }

    try {
        // Fetch all dashboard data in a single API call — the backend aggregates it
        const res = await fetch(`${API}/analytics/dashboard`, { headers: authHeaders() });
        if (res.status === 401) { handleLogout(); return; }  // token expired — force re-login
        if (!res.ok) throw new Error('Failed to load analytics');
        const data = await res.json();

        // Update "last refreshed" timestamp shown in the dashboard header
        const updEl = document.getElementById('dash-last-updated');
        if (updEl) {
            const now = new Date();
            updEl.textContent = 'Updated ' + now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        }

        // Render each dashboard section with its data slice
        renderKPIs(data.kpis);                        // top headline cards
        // Use the existing flight data to generate alerts dynamically
        if (typeof allFlights !== 'undefined' && allFlights.length > 0) {
            renderOperationalAlerts(allFlights);
        } else {
            // Fallback: fetch flights if they haven't been loaded yet
            fetch(`${API}/flights`, { headers: authHeaders() })
                .then(r => r.json())
                .then(f => renderOperationalAlerts(f))
                .catch(e => console.error("Alerts fallback failed", e));
        }
        renderEmailBatches(data.batch_emails);        // batch email monitor

        // Only render Chart.js charts if the library is loaded on the page
        if (window.Chart) {
            renderStatusChart(data.status_distribution);   // doughnut: flight status breakdown
            renderAirlineChart(data.airline_flights);       // bar: flights per airline
            renderAirportChart(data.airport_comparison);   // horizontal bar: flights per airport
        } else {
            // Chart.js CDN failed to load — show a fallback message
            console.error('[Analytics] Chart.js not loaded.');
            document.querySelectorAll('.chart-wrapper').forEach(c => {
                c.innerHTML = '<p style="text-align:center;padding:20px;color:var(--text3)">Chart engine unavailable.</p>';
            });
        }
    } catch (err) {
        // Show error in the KPI grid so the dashboard doesn't silently break
        console.error('[Analytics]', err);
        if (kpiGrid) kpiGrid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: #ef4444;">Failed to load dashboard: ${err.message}</div>`;
    }
}

function renderKPIs(kpis) {
    const grid = document.getElementById('analytics-kpis');
    if (!grid) return;

    // Define KPI card metadata — icon, label, value from API, and accent color
    const cards = [
        { icon: '✈️',  label: 'Total Flights',   value: kpis.total_flights,   color: '#0f3460' },
        { icon: '🟢',  label: 'Active Flights',  value: kpis.active_flights,  color: '#0ea5e9' },
        { icon: '⚠️',  label: 'Delayed Flights', value: kpis.delayed_flights, color: '#f59e0b' },
        { icon: '🛫',  label: 'Boarding Flights',value: kpis.boarding_flights, color: '#10b981' },
        { icon: '✅',  label: 'Arrived Flights', value: kpis.arrived_flights,  color: '#065f46' },
        { icon: '🏢',  label: 'Active Airlines', value: kpis.active_airlines,  color: '#6366f1' },
    ];

    // Render each card as a styled div with a CSS custom property for the accent border color
    grid.innerHTML = cards.map(c => `
        <div class="kpi-card" style="--kpi-accent:${c.color}">
            <span class="kpi-icon">${c.icon}</span>
            <div class="kpi-value" style="color:${c.color}">${c.value}</div>
            <div class="kpi-label">${c.label}</div>
        </div>
    `).join('');
}

function renderOperationalAlerts(flights) {
    const container = document.getElementById("operational-alerts-list");
    const badge = document.getElementById("alerts-count-badge");
    if (!container) return;

    const flightData = Array.isArray(flights) ? flights : [];
    
    const delayedAlerts = [];
    const cancelledAlerts = [];
    const boardingAlerts = [];
    const arrivedAlerts = [];
    const seen = new Set();
    
    // Mapping of delay reasons to styles/icons
    const reasonConfig = {
        "Weather":      { icon: "🌦️", class: "ops-alert-weather" },
        "Technical":    { icon: "🔧", class: "ops-alert-technical" },
        "ATC":          { icon: "🗼", class: "ops-alert-atc" },
        "Crew":         { icon: "👨‍✈️", class: "ops-alert-crew" },
        "Security":     { icon: "🚨", class: "ops-alert-security" },
        "Late Arrival": { icon: "⏰", class: "ops-alert-late" },
        "Operational":  { icon: "⚠️", class: "ops-alert-other" },
        "Other":        { icon: "⚠️", class: "ops-alert-other" }
    };

    flightData.forEach(f => {
        const key = `${f.flight_number}:${f.status}`;
        if (seen.has(key)) return;

        if (f.status === "Delayed") {
            seen.add(key);
            const reason = f.delay_reason || "Other";
            const config = reasonConfig[reason] || reasonConfig["Other"];
            const mins = f.delay_minutes;
            const timeStr = (mins && mins > 0) ? `${mins} min` : "Time not specified";
            
            delayedAlerts.push({
                type: config.class,
                icon: config.icon,
                title: `${f.flight_number} Delayed`,
                subtitle: `${timeStr} • ${reason} • Gate ${f.gate_number || '—'}`
            });
        } else if (f.status === "Cancelled") {
            seen.add(key);
            cancelledAlerts.push({
                type: "ops-alert-cancelled",
                icon: "❌",
                title: `${f.flight_number} Cancelled`,
                subtitle: `Operational disruption • Gate ${f.gate_number || '—'}`
            });
        } else if (f.status === "Boarding") {
            seen.add(key);
            boardingAlerts.push({
                type: "ops-alert-boarding",
                icon: "🛫",
                title: `${f.flight_number} Boarding`,
                subtitle: `Gate ${f.gate_number} • Final call`
            });
        } else if (f.status === "Arrived" && f.carousel_number) {
            seen.add(key);
            arrivedAlerts.push({
                type: "ops-alert-arrived",
                icon: "✅",
                title: `${f.flight_number} Arrived`,
                subtitle: `Baggage at Carousel ${f.carousel_number}`
            });
        }
    });

    // Create a balanced mix (All delays + Limited others)
    const displayAlerts = [
        ...delayedAlerts,
        ...boardingAlerts.slice(0, 3),
        ...cancelledAlerts.slice(0, 3),
        ...arrivedAlerts.slice(0, 2)
    ];

    const html = displayAlerts.map(a => `
        <div class="ops-alert ${a.type}">
            <div class="ops-alert-icon">${a.icon}</div>
            <div class="ops-alert-content">
                <div class="ops-alert-title">${a.title}</div>
                <div class="ops-alert-subtitle">${a.subtitle}</div>
            </div>
        </div>
    `).join("");

    const total = delayedAlerts.length + cancelledAlerts.length + boardingAlerts.length + arrivedAlerts.length;
    container.innerHTML = html || '<div class="empty-alert">No active operational alerts</div>';

    if (badge) {
        badge.textContent = total || "";
        badge.style.display = total > 0 ? 'inline-block' : 'none';
    }
}

function renderEmailBatches(batches) {
    const container = document.getElementById('email-batches-container');
    if (!container) return;

    // Show placeholder if no batch data is available from the backend
    if (!batches || batches.length === 0) {
        container.innerHTML = '<p class="text-muted">No batch data available.</p>';
        return;
    }

    // Each batch object: { batch, time, flights, status }
    // status is SCHEDULED / PENDING / SENT — CSS class batch-{status} controls the color
    container.innerHTML = batches.map(b => `
        <div class="email-batch-item">
            <div class="email-batch-info">
                <h4>${b.batch}</h4>
                <p>${b.time} &bull; ${b.flights} flights</p>
            </div>
            <!-- batch-SENT = green, batch-PENDING = orange, batch-SCHEDULED = grey -->
            <div class="batch-status batch-${b.status}">${b.status}</div>
        </div>
    `).join('');
}

function renderStatusChart(data) {
    const ctx = document.getElementById('statusChart');
    if (!ctx) return;

    // Destroy the previous chart instance before creating a new one.
    // Without this, Chart.js throws a "Canvas already in use" error on each refresh.
    if (statusChartInstance) { statusChartInstance.destroy(); statusChartInstance = null; }

    const labels = data.map(d => d.status);  // e.g. ['Scheduled', 'Boarding', 'Delayed']
    const counts = data.map(d => d.count);   // corresponding counts

    // Map each status to its branded color (matches status badges in the flight table)
    const colors = labels.map(s => {
        if (s === 'Scheduled') return '#0369a1';
        if (s === 'Boarding')  return '#10b981';
        if (s === 'Departed')  return '#6366f1';
        if (s === 'Arrived')   return '#065f46';
        if (s === 'Delayed')   return '#f59e0b';
        if (s === 'Cancelled') return '#ef4444';
        return '#cbd5e1';  // fallback grey for unknown statuses
    });

    // Doughnut chart — good for showing proportional distribution at a glance
    statusChartInstance = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels,
            datasets: [{
                data: counts,
                backgroundColor: colors,
                borderWidth: 2,       // thin white border between segments
                borderColor: '#fff',
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,  // fills the container div's height
            plugins: {
                legend: { position: 'bottom', labels: { padding: 12, font: { size: 11 } } }
            },
            cutout: '62%'  // larger cutout = thinner ring (donut style)
        }
    });
}

function renderAirlineChart(data) {
    const ctx = document.getElementById('airlineChart');
    if (!ctx) return;

    // Destroy stale chart before re-rendering to avoid the "Canvas already in use" error
    if (airlineChartInstance) { airlineChartInstance.destroy(); airlineChartInstance = null; }

    // Rotating color palette — up to 5 airlines, cycles if more are added
    const palette = ['#0ea5e9', '#6366f1', '#10b981', '#f59e0b', '#ef4444'];

    // Build human-readable labels: "6E • IndiGo" format for each airline
    const airlineLabels = data.map(d => {
        const code = d.airline_code || d.code || '';
        const name = d.airline_name || d.name || d.airline || '';
        return code && name ? `${code} • ${name}` : (name || code || 'Unknown');
    });

    airlineChartInstance = new Chart(ctx, {
        type: 'bar',   // vertical bar chart — easy to compare airline sizes
        data: {
            labels: airlineLabels,
            datasets: [{
                label: 'Flights',
                data: data.map(d => d.count),
                backgroundColor: data.map((_, i) => palette[i % palette.length]),  // cycle palette
                borderRadius: 6,       // rounded top corners on bars
                borderSkipped: false,  // apply radius to all corners (not just top)
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },   // labels are already on the X axis
                tooltip: {
                    callbacks: {
                        // Custom tooltip showing both airline code+name and flight count
                        label: function(context) {
                            const d    = data[context.dataIndex];
                            const code = d.airline_code || d.code || '??';
                            const name = d.airline_name || d.name || d.airline || 'Unknown';
                            return [
                                `Airline: ${code} • ${name}`,
                                `Total Flights: ${d.count}`
                            ];
                        }
                    }
                }
            },
            scales: {
                y: { beginAtZero: true, grid: { color: '#f1f5f9' }, ticks: { font: { size: 11 } } },
                x: { grid: { display: false }, ticks: { font: { size: 11 } } }
            }
        }
    });
}

function renderAirportChart(data) {
    const ctx = document.getElementById('airportChart');
    if (!ctx) return;

    // Destroy stale instance to prevent Chart.js canvas conflicts on re-render
    if (airportChartInstance) { airportChartInstance.destroy(); airportChartInstance = null; }

    airportChartInstance = new Chart(ctx, {
        type: 'bar',   // horizontal bar — better for comparing named categories
        data: {
            labels: data.map(d => d.airport),           // IATA codes on Y axis
            datasets: [{
                label: 'Active Flights',
                data: data.map(d => d.active_flights),  // count on X axis
                backgroundColor: '#f59e0b',  // amber — stands out, represents active/live traffic
                borderRadius: 6,
                borderSkipped: false,
            }]
        },
        options: {
            indexAxis: 'y',    // flip to horizontal bar layout
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },   // label is self-explanatory
            scales: {
                x: { beginAtZero: true, grid: { color: '#f1f5f9' }, ticks: { font: { size: 11 } } },
                y: { grid: { display: false },          ticks: { font: { size: 11 } } }
            }
        }
    });
}

// ── Admin Profile ────────────────────────────────────────────────
let originalAdminData = {};

async function loadAdminProfile() {
    try {
        const res = await fetch(`${API}/auth/me`, { headers: authHeaders() });
        if (!res.ok) return;
        const user = await res.json();
        
        originalAdminData = {
            full_name: user.full_name || '',
            email: user.email || ''
        };

        document.getElementById('admin-fullname').value = user.full_name || '';
        document.getElementById('admin-username').value = user.username || '';
        document.getElementById('admin-email').value = user.email || '';
        
        document.getElementById('admin-created-at').value = user.created_at || 'N/A';
        document.getElementById('admin-last-login').value = user.last_login_at || 'N/A';
        document.getElementById('admin-last-password-change').value = user.last_password_changed_at || 'N/A';
        
        toggleAdminEditMode(false); // Reset to read-only
    } catch (err) { console.error(err); }
}

function toggleAdminEditMode(isEditing) {
    const fn = document.getElementById('admin-fullname');
    const em = document.getElementById('admin-email');
    const actions = document.getElementById('admin-profile-actions');
    const editBtn = document.getElementById('admin-edit-btn');
    const msg = document.getElementById('admin-msg-profile');

    if (isEditing) {
        fn.disabled = false;
        fn.style.background = '#fff';
        fn.style.color = 'var(--text)';
        
        em.disabled = false;
        em.style.background = '#fff';
        em.style.color = 'var(--text)';
        
        actions.style.display = 'flex';
        editBtn.style.display = 'none';
        if (msg) msg.style.display = 'none';
    } else {
        // Restore original if cancelling
        fn.value = originalAdminData.full_name || '';
        em.value = originalAdminData.email || '';
        
        fn.disabled = true;
        fn.style.background = '#f8f9fc';
        fn.style.color = '#718096';
        
        em.disabled = true;
        em.style.background = '#f8f9fc';
        em.style.color = '#718096';
        
        actions.style.display = 'none';
        editBtn.style.display = 'block';
    }
}

async function saveAdminProfile() {
    const fn = document.getElementById('admin-fullname').value.trim();
    const em = document.getElementById('admin-email').value.trim();
    const msgBox = document.getElementById('admin-msg-profile');

    if (!fn || !em) {
        msgBox.textContent = "Full Name and Email are required.";
        msgBox.className = "msg-box msg-error";
        msgBox.style.display = "block";
        return;
    }

    if (!window.confirm("Are you sure you want to update your profile information?")) return;

    try {
        const res = await fetch(`${API}/auth/me/profile`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify({ full_name: fn, email: em })
        });
        if (!res.ok) {
            const e = await res.json();
            throw new Error(e.detail || "Update failed");
        }
        
        msgBox.textContent = "Profile updated successfully!";
        msgBox.className = "msg-box msg-success";
        msgBox.style.display = "block";
        
        // Update original data
        originalAdminData.full_name = fn;
        originalAdminData.email = em;
        
        // Update top-right pill
        fullName = fn;
        localStorage.setItem('fullName', fn);
        setupNavbar();
        
        setTimeout(() => toggleAdminEditMode(false), 1500);
    } catch (err) {
        msgBox.textContent = err.message;
        msgBox.className = "msg-box msg-error";
        msgBox.style.display = "block";
    }
}

async function changeAdminPassword() {
    const current = document.getElementById('admin-current-password').value;
    const newPw = document.getElementById('admin-new-password').value;
    const confirm = document.getElementById('admin-confirm-password').value;
    const btn = document.getElementById('btn-admin-pw');
    const msgBox = document.getElementById('admin-msg-pw');

    const showMsg = (msg, type) => {
        msgBox.textContent = msg;
        msgBox.className = `msg-box msg-${type}`;
        msgBox.style.display = 'block';
    };

    if (!current) { showMsg('Please enter your current password.', 'error'); return; }
    if (newPw !== confirm) { showMsg('New passwords do not match.', 'error'); return; }
    
    const adminUsername = document.getElementById('admin-username').value;
    const adminEmail = document.getElementById('admin-email').value;
    const adminFullName = document.getElementById('admin-fullname').value;
    
    const pwError = validateStrongPassword(newPw, adminUsername, adminEmail, adminFullName);
    if (pwError) { showMsg(pwError, 'error'); return; }
    
    if (!window.confirm('Are you sure you want to change your password?')) return;

    btn.disabled = true;
    btn.textContent = 'Updating...';

    try {
        const res = await fetch(`${API}/auth/me/change-password`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify({ current_password: current, new_password: newPw }),
        });
        if (!res.ok) {
            const e = await res.json().catch(() => ({}));
            throw new Error(parseApiError(e, 'Password update failed'));
        }
        
        showMsg('Password updated successfully! Confirmation email sent.', 'success');
        document.getElementById('admin-current-password').value = '';
        document.getElementById('admin-new-password').value = '';
        document.getElementById('admin-confirm-password').value = '';
    } catch (err) {
        showMsg(err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Update Password';
    }
}