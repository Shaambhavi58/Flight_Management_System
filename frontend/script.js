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
        airports
    .filter(a => a.code === 'HYD')
    .forEach(a => {
            const opt = document.createElement('option');
            opt.value = a.id;
            opt.textContent = `${a.name} (${a.code})`;
            sel.appendChild(opt);
        });
    } catch (err) { console.error(err); }
}

window.openAirlineOperations = function(airline) {
    localStorage.removeItem("selectedAirline");
    localStorage.removeItem("activeAirline");
    
    selectedAirline = airline.name;
    activeAirline = airline.code;
    localStorage.setItem("selectedAirline", airline.name);
    localStorage.setItem("activeAirline", airline.code);
    
    const storedAirport = localStorage.getItem('selectedAirport');
    if (storedAirport) {
        selectedAirport = JSON.parse(storedAirport);
    }
    
    activeCategory = "arrival";
    activeTerminal = "ALL";
    activeStatusFilter = "ALL";
    
    allFlights = [];
    window.isFlightsLoading = true;
    
    console.log("OPEN AIRLINE:", selectedAirline, activeAirline);
    
    showPage('flights');
};

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
        if (!grid) return;
        grid.innerHTML = '';

        // Safely extract HYD airport object
        const hydAirport = airports.find(a => String(a.code || '').trim().toUpperCase() === 'HYD');

        if (!hydAirport) {
            console.error("HYD Airport not found in airports list");
            grid.innerHTML = `
                <div style="grid-column: 1/-1; text-align: center; padding: 40px; color: #ef4444; font-weight: bold; background: #fee2e2; border-radius: 8px; border: 1px solid #fecaca;">
                    Hyderabad (HYD) Airport operational data is currently unavailable. Please contact the administrator.
                </div>`;
            return;
        }

        // Define Hyderabad specific airlines with exact filenames
        const airlines = [
            { name: 'IndiGo',            code: '6E',  image: 'indigo.png'           },
            { name: 'Air India',         code: 'AI',  image: 'airindia.png'         },
            { name: 'Akasa Air',         code: 'QP',  image: 'akasa.png'            },
            { name: 'Emirates',          code: 'EK',  image: 'emirates.png'         },
            { name: 'Qatar Airways',     code: 'QA',  image: 'qatar.png'            },
            { name: 'Air India Express', code: 'AI1', image: 'airindia express.png' },
            { name: 'Alliance Air',      code: 'AA1', image: 'allianceair.png'      },
            { name: 'Fly91',             code: 'F',   image: 'fly91.png'            }
        ];

        airlines.forEach(a => {
            const card = document.createElement('div');
            card.className = 'airport-card airline-selection-card';
            card.setAttribute("data-airline", a.name);
            card.innerHTML = `
                <div class="airport-card-img-wrapper">
                    <div class="airport-card-img">
                        <img src="/static/${a.image}" alt="${a.name}">
                    </div>
                </div>
                <div class="airport-card-body">
                    <span class="airport-code-badge airline-code-badge">${a.code}</span>
                    <h3>${a.name}</h3>
                    <p class="text-muted">Hyderabad Operations</p>
                </div>
            `;

            card.onclick = () => {
                localStorage.setItem('selectedAirport', JSON.stringify(hydAirport));
                window.openAirlineOperations({ name: a.name, code: a.code });
            };

            grid.appendChild(card);
        });

    } catch (err) { 
        console.error(err); 
    }
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
    selectedAirline = localStorage.getItem("selectedAirline");
    activeAirline = localStorage.getItem("activeAirline") || "ALL";
    console.log("SETUP PAGE:", selectedAirline, activeAirline);

    document.getElementById('bc-airport').textContent = selectedAirport.city;
    document.getElementById('flight-page-title').innerHTML =
        `${selectedAirport.name} <span style="color:var(--cyan);font-size:18px">(${selectedAirport.code})</span>`;
    document.getElementById('flight-page-sub').textContent = selectedAirline
        ? `${selectedAirport.city} — ${selectedAirline} Operations`
        : `${selectedAirport.city} — Flight Board`;
    document.getElementById('f-destination').value =
        `${selectedAirport.city} (${selectedAirport.code})`;

    document.getElementById('btn-add-flight').classList.toggle('hidden', role === 'viewer');
    document.getElementById('btn-sync-live').classList.toggle('hidden', role !== 'admin');

    if (!activeCategory || activeCategory === 'info') {
        activeCategory = 'arrival';
    }
    document.querySelectorAll('.category-card').forEach(c => c.classList.remove('active'));
    const activeCatEl = document.querySelector(`[data-type="${activeCategory}"]`);
    if (activeCatEl) activeCatEl.classList.add('active');
    document.getElementById('flight-board-section').classList.remove('hidden');
    document.querySelectorAll('.tab-btn').forEach((b, i) => b.classList.toggle('active', i === 0));
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
    document.getElementById('flight-board-section').classList.remove('hidden');
    renderBoard();
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
        window.isFlightsLoading = false;
        renderBoard();
    } catch (err) {
        console.error(err);
        window.isFlightsLoading = false;
        renderBoard();
    }
}

// Deleted obsolete airline functions

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
    'YYZ': 'Toronto',
    'IXB': 'Bagdogra',
    'MCT': 'Muscat',
    'IST': 'Istanbul',
    'ADD': 'Addis Ababa',
    'CMB': 'Colombo',
    'JED': 'Jeddah',
    'TRV': 'Thiruvananthapuram',
    'VTZ': 'Visakhapatnam',
    'TIR': 'Tirupati',
    'VGA': 'Vijayawada',
    'RJA': 'Rajahmundry',
    'PAT': 'Patna',
    'BBI': 'Bhubaneswar',
    'NAG': 'Nagpur',
    'RPR': 'Raipur',
    'CJB': 'Coimbatore'

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

/**
 * formatSingleCity(str)
 * Converts a full airport name like "Indira Gandhi International (DEL)" into
 * just the clean city label "Delhi (DEL)". Falls back to the raw string if
 * no IATA code can be extracted.
 */
function formatSingleCity(str) {
    if (!str) return '-';
    const iataMatch = str.match(/\(([A-Z]{3})\)/);
    if (!iataMatch) return str;
    const iata = iataMatch[1];
    const city = IATA_CITY_MAP[iata] || str.split('(')[0].trim();
    return `${city} (${iata})`;
}

function renderBoard() {
    if (window.isFlightsLoading) {
        const empty = document.getElementById('empty-state');
        const wrapper = document.getElementById('table-wrapper');
        const tbody = document.getElementById('flights-tbody');
        if (empty) empty.classList.add('hidden');
        if (wrapper) wrapper.style.display = 'block';
        if (tbody) tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding: 40px; font-weight: bold; color: var(--text3);">Loading flights...</td></tr>';
        ['stat-total', 'stat-arrived', 'stat-boarding', 'stat-scheduled', 'stat-delayed'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.textContent = '...';
        });
        return;
    }

    let filtered = allFlights.filter(f => f.flight_type === activeCategory);

    if (activeTerminal !== 'ALL') {
        filtered = filtered.filter(f => f.terminal_number === activeTerminal);
    }

    console.log("RENDER FILTER CODE:", activeAirline);

    if (activeAirline && activeAirline !== 'ALL') {
        const targetCode = String(activeAirline).toUpperCase();
        filtered = filtered.filter(f => f.airline_code && String(f.airline_code).toUpperCase() === targetCode);
    }

    console.log("FILTERED SAMPLE:", filtered.slice(0, 3));

    const isArrival = activeCategory === 'arrival';

    filtered.sort((a, b) => {
        const timeA = isArrival ? (a.arrival_time || '') : (a.departure_time || '');
        const timeB = isArrival ? (b.arrival_time || '') : (b.departure_time || '');
        return timeA.localeCompare(timeB);
    });

    document.getElementById('stat-total').textContent = filtered.length;
    document.getElementById('stat-arrived').textContent =
        filtered.filter(f => f.status.toLowerCase() === 'arrived').length;
    document.getElementById('stat-boarding').textContent =
        filtered.filter(f => f.status.toLowerCase() === 'boarding').length;
    document.getElementById('stat-scheduled').textContent =
        filtered.filter(f => f.status.toLowerCase() === 'scheduled').length;
    document.getElementById('stat-delayed').textContent =
        filtered.filter(f => f.status.toLowerCase() === 'delayed').length;

    if (activeStatusFilter !== 'ALL') {
        const target = activeStatusFilter.toLowerCase();
        filtered = filtered.filter(f => f.status.toLowerCase() === target);
    }

    const tbody = document.getElementById('flights-tbody');
    const empty = document.getElementById('empty-state');
    const wrapper = document.getElementById('table-wrapper');

    if (filtered.length === 0) {
        empty.classList.remove('hidden');
        wrapper.style.display = 'none';
    } else {
        empty.classList.add('hidden');
        wrapper.style.display = 'block';
    }

    const showActions = role === 'admin' || role === 'staff';
    const actionsHeader = showActions ? `<th class="cell-actions">Actions</th>` : '';
    const thead = document.getElementById('flights-thead');

    if (isArrival) {
        thead.innerHTML = `
        <tr>
            <th>Flight</th>
            <th>Airline</th>
            <th>Origin</th>
            <th>Arrival</th>
            <th>Terminal</th>
            <th>Carousel</th>
            <th>Status</th>
            ${actionsHeader}
        </tr>`;
    } else {
        thead.innerHTML = `
        <tr>
            <th>Flight</th>
            <th>Airline</th>
            <th>Destination</th>
            <th>Departure</th>
            <th>Gate</th>
            <th>Terminal</th>
            <th>Make-Up Area</th>
            <th>Status</th>
            ${actionsHeader}
        </tr>`;
    }

    tbody.innerHTML = '';

    filtered.forEach(f => {
        const tr = document.createElement('tr');
        tr.dataset.flightId = f.id; // used by viewFlight() to scroll & highlight

        const terminalDisplay = f.terminal_number || '-';
        const terminalBadge = terminalDisplay !== '-'
            ? `<span class="terminal-badge terminal-${terminalDisplay}">${terminalDisplay}</span>`
            : `<span class="carousel-na">-</span>`;

        let rowHtml = '';

        const airlineHtml = `
            <td class="cell-airline-info">
                <div class="cell-airline">
                    <span class="airline-badge badge-${f.airline_code}">${f.airline_code}</span>
                    ${f.airline_name}
                </div>
            </td>`;

        let actions = '';
        if (showActions) {
            if (role === 'admin') {
                actions = `
                <td class="cell-actions">
                    <div class="action-container">
                        <button class="action-btn btn-edit" onclick="editFlight(${f.id})">Edit</button>
                        <button class="action-btn btn-delete" onclick="deleteFlight(${f.id})">Delete</button>
                    </div>
                </td>`;
            } else {
                actions = `
                <td class="cell-actions">
                    <div class="action-container">
                        <button class="action-btn btn-edit" onclick="editFlight(${f.id})">Edit</button>
                    </div>
                </td>`;
            }
        }

        if (isArrival) {
            const originClean = formatSingleCity(f.origin);
            const carousel = f.carousel_number || getCarousel(f.flight_number, f.terminal_number);

            rowHtml = `
                <td class="cell-flight">${f.flight_number}</td>
                ${airlineHtml}
                <td class="cell-route">${originClean}</td>
                <td class="cell-time">${f.arrival_time || '-'}</td>
                <td class="cell-terminal-info">${terminalBadge}</td>
                <td class="cell-carousel">
                    <span class="carousel-badge">${carousel}</span>
                </td>
                <td class="cell-status">${renderStatusCell(f)}</td>
                ${actions}`;
        } else {
            const destClean = formatSingleCity(f.destination);
            const gateDisplay = f.gate_number || '-';
            const makeupArea = f.makeup_area || '-';

            rowHtml = `
                <td class="cell-flight">${f.flight_number}</td>
                ${airlineHtml}
                <td class="cell-route">${destClean}</td>
                <td class="cell-time">${f.departure_time || '-'}</td>
                <td class="cell-gate">${gateDisplay}</td>
                <td class="cell-terminal-info">${terminalBadge}</td>
                <td class="cell-carousel">
                    <span class="makeup-badge">${makeupArea}</span>
                </td>
                <td class="cell-status">${renderStatusCell(f)}</td>
                ${actions}`;
        }

        tr.innerHTML = rowHtml;
        tbody.appendChild(tr);
    });

    // ── viewFlight() highlight ─────────────────────────────────────
    if (pendingHighlightFlightId) {
        const targetRow = tbody.querySelector(`tr[data-flight-id="${pendingHighlightFlightId}"]`);
        if (targetRow) {
            pendingHighlightFlightId = null;
            setTimeout(() => {
                targetRow.scrollIntoView({ behavior: 'smooth', block: 'center' });
                targetRow.classList.add('flight-highlight');
                setTimeout(() => targetRow.classList.remove('flight-highlight'), 4000);
            }, 120);
        } else {
            // Flight not visible under current filters — will be cleared after one attempt
            pendingHighlightFlightId = null;
            showToast('Flight not found or no longer active.', 'error');
        }
    }
}

function renderStatusCell(f) {
    return `<span class="status-badge status-${f.status.replace(/\s+/g, '-')}">${f.status}</span>`;
}

async function clearGateAlert(event, flightId) {
    event.stopPropagation();
    try {
        const res = await fetch(`${API}/flights/${flightId}/clear-gate-alert`, {
            method: 'PATCH',
            headers: authHeaders()
        });
        if (!res.ok) throw new Error('Failed');
        // Optimistically update local data so badge vanishes immediately
        const f = allFlights.find(x => x.id === flightId);
        if (f) { f.gate_changed = false; f.previous_gate = null; }
        renderBoard();
        showToast('Gate alert cleared', 'success');
    } catch (err) {
        showToast('Could not clear gate alert', 'error');
    }
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
            <select id="edit-gate" class="form-control" style="width:100%; padding:8px; border-radius:6px; border:1px solid var(--gray3);">
                <option value="${flight.gate_number}" selected>${flight.gate_number}</option>
            </select>
            <small class="text-muted" id="gate-loading-indicator" style="display:block; margin-top:6px; font-size:11px;">Loading available gates...</small>
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

        <div style="margin-top:24px;">
            <h4 style="font-size:14px; margin-bottom:12px; color:var(--navy);">Status History</h4>
            <div id="flight-history-timeline">
                <p style="color:var(--text3);font-size:12px;">Loading history...</p>
            </div>
        </div>
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

    fetchFlightHistory(id);
    fetchAvailableGates(flight.airport_id, flight.terminal_number, flight.departure_time, flight.arrival_time, flight.gate_number, flight.id);
}

async function fetchAvailableGates(airportId, terminal, startTime, endTime, currentGate, flightId) {
    const indicator = document.getElementById('gate-loading-indicator');
    const select = document.getElementById('edit-gate');
    if (!select) return;

    try {
        const url = `${API}/gates/available?airport_id=${airportId}&terminal=${terminal}&start_time=${startTime}&end_time=${endTime}&flight_id=${flightId}`;
        const res = await fetch(url, { headers: authHeaders() });
        if (!res.ok) throw new Error('Failed to load available gates');
        const gates = await res.json();

        // Populate select options
        select.innerHTML = '';
        
        // Ensure current gate is always the first, active choice
        let optionsHtml = `<option value="${currentGate}" selected>${currentGate} (Current)</option>`;
        
        gates.forEach(g => {
            if (g.gate_number !== currentGate) {
                optionsHtml += `<option value="${g.gate_number}">${g.gate_number}</option>`;
            }
        });
        
        select.innerHTML = optionsHtml;
        if (indicator) {
            indicator.textContent = `Available Gates: ${gates.map(g => g.gate_number).join(', ') || 'None (only current)'}`;
            indicator.style.color = '#16a34a';
        }
    } catch (err) {
        console.error(err);
        if (indicator) {
            indicator.textContent = 'Could not load available gates.';
            indicator.style.color = 'red';
        }
    }
}

async function fetchFlightHistory(id) {
    try {
        const res = await fetch(`${API}/flights/${id}/history`, { headers: authHeaders() });
        if (!res.ok) throw new Error('Failed to load history');
        const history = await res.json();
        
        const container = document.getElementById('flight-history-timeline');
        if (!container) return;
        
        if (history.length === 0) {
            container.innerHTML = '<p style="color:var(--text3);font-size:13px;padding:8px 0;">No status changes recorded.</p>';
            return;
        }
        
        let html = '<div class="timeline-container">';
        history.forEach(h => {
            const time = new Date(h.changed_at).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});
            const oldS = h.old_status ? h.old_status + ' → ' : '';
            html += `
                <div class="timeline-item">
                    <div class="timeline-dot"></div>
                    <div class="timeline-content">
                        <div class="timeline-status">${oldS}${h.new_status}</div>
                        <div class="timeline-meta">${time} · ${h.changed_by}</div>
                        ${h.reason ? `<div class="timeline-reason">${h.reason}</div>` : ''}
                    </div>
                </div>
            `;
        });
        html += '</div>';
        container.innerHTML = html;
    } catch (err) {
        console.error(err);
        const container = document.getElementById('flight-history-timeline');
        if (container) container.innerHTML = '<p style="color:red;font-size:12px;">Error loading history.</p>';
    }
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
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || "Update failed");
        }

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

let terminalChartInstance = null;
let trafficChartInstance = null;
let pendingHighlightFlightId = null; // set by viewFlight() — consumed by renderBoard()
let carouselChartInstance = null;

async function triggerTestEmailBatch() {
    const btn = document.getElementById('trigger-test-email-btn');
    if (!btn) return;

    btn.disabled = true;
    const originalText = btn.innerHTML;
    btn.innerHTML = '⏳ Dispatched Sync Request...';

    try {
        const res = await fetch(`${API}/analytics/trigger-test-email`, {
            method: 'POST',
            headers: authHeaders()
        });
        const data = await res.json();

        if (res.ok && data.status === 'success') {
            showToast(data.message || 'Manual Batch Email Alert Triggered Successfully!', 'success');
        } else {
            showToast(data.message || 'Failed to dispatch manual email sync.', 'error');
        }
    } catch (err) {
        console.error('[BatchEmailSync] Error:', err);
        showToast('System connectivity error. Please try again later.', 'error');
    } finally {
        setTimeout(() => {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }, 3000);
    }
}

async function loadAnalytics() {
    // Show a loading placeholder in the KPI grid on the first render
    const kpiGrid = document.getElementById('analytics-kpis');
    if (kpiGrid && (!kpiGrid.innerHTML.trim() || kpiGrid.innerHTML.includes('Failed to load dashboard'))) {
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
        // ── Step 3: Fetch fresh flight list for Operational Alerts ──────────
        // Enforce live data sourcing from the selected airport to prevent stale/cached alerts.
        const airportId = selectedAirport ? selectedAirport.id : userAirportId;
        const flightUrl = airportId ? `${API}/airports/${airportId}/flights` : `${API}/flights`;
        
        let fetchedFlights = [];
        const flightRes = await fetch(flightUrl, { headers: authHeaders() });
        if (flightRes.ok) {
            fetchedFlights = await flightRes.json();
            // Verification log for operational data integrity
            console.log("Live analytics source", fetchedFlights.filter(f => f.status === "Delayed"));
            renderOperationalAlerts(data.live_alerts);
            renderTopDelayedFlights(fetchedFlights);
            renderDelaySeveritySummary(fetchedFlights);
        }

        renderEmailBatches(data.batch_emails);        // batch email monitor

        // Only render Chart.js charts if the library is loaded on the page
        if (window.Chart) {
            renderStatusChart(data.status_distribution);   // doughnut: flight status breakdown
            renderAirlineChart(data.airline_flights);       // bar: flights per airline
            renderAirportChart(data.airport_comparison);   // horizontal bar: flights per airport
            renderTerminalChart(data.terminal_distribution); // doughnut: terminal breakdown
            renderGateInfrastructure(data.gate_distribution); // progress bars: gate health
            renderTrafficChart(data.hourly_traffic);       // bar: hourly traffic peaks
            renderCarouselChart(data.carousel_utilization); // horizontal bar: carousel utilization
            if (fetchedFlights.length > 0) {
                // Future use
            }
        } else {
            // Chart.js CDN failed to load — show a fallback message
            console.error('[Analytics] Chart.js not loaded.');
            document.querySelectorAll('.chart-wrapper').forEach(c => {
                c.innerHTML = '<p style="text-align:center;padding:20px;color:var(--text3)">Chart engine unavailable.</p>';
            });
        }
    } catch (err) {
        console.error('[Analytics]', err);
        if (kpiGrid && (!kpiGrid.innerHTML.trim() || kpiGrid.innerHTML.includes('Loading operational data'))) {
            kpiGrid.innerHTML = `<div style="grid-column: 1/-1; text-align: center; padding: 40px; color: #ef4444;">Failed to load dashboard: ${err.message}</div>`;
        } else {
            if (typeof showToast === 'function') {
                showToast('Failed to sync analytics data. Retrying...', 'error');
            }
        }
    }
}
function renderKPIs(kpis) {
    const grid = document.getElementById('analytics-kpis');
    if (!grid || !kpis) return;

    // Check if grid already has the cards rendered to prevent flicker
    const existingCards = grid.querySelectorAll('.kpi-card');
    if (existingCards.length === 11) {
        const values = grid.querySelectorAll('.kpi-value');
        if (kpis.total_flights !== undefined) values[0].textContent = kpis.total_flights;
        if (kpis.active_flights !== undefined) values[1].textContent = kpis.active_flights;
        if (kpis.delayed_flights !== undefined) values[2].textContent = kpis.delayed_flights;
        if (kpis.boarding_flights !== undefined) values[3].textContent = kpis.boarding_flights;
        if (kpis.scheduled_flights !== undefined) values[4].textContent = kpis.scheduled_flights;
        if (kpis.cancelled_flights !== undefined) values[5].textContent = kpis.cancelled_flights;
        if (kpis.arrived_flights !== undefined) values[6].textContent = kpis.arrived_flights;
        if (kpis.departure_flights !== undefined) values[7].textContent = kpis.departure_flights;
        if (kpis.active_carousels !== undefined) values[8].textContent = kpis.active_carousels;
        if (kpis.avg_delay_duration !== undefined) values[9].textContent = `${kpis.avg_delay_duration} min`;
        if (kpis.on_time_percentage !== undefined) values[10].textContent = `${kpis.on_time_percentage}%`;
        return;
    }

    const cards = [
        { icon: '✈️',  label: 'Total Flights', value: kpis.total_flights ?? '...', color: '#0f3460' },
        { icon: '🟢',  label: 'Active Flights', value: kpis.active_flights ?? '...', color: '#0ea5e9' },
        { icon: '⚠️',  label: 'Delayed Flights', value: kpis.delayed_flights ?? '...', color: '#f59e0b' },
        { icon: '📢',  label: 'Boarding Flights', value: kpis.boarding_flights ?? '...', color: '#10b981' },
        { icon: '📅',  label: 'Scheduled Flights', value: kpis.scheduled_flights ?? '...', color: '#6b7280' },
        { icon: '❌',  label: 'Cancelled Flights', value: kpis.cancelled_flights ?? '...', color: '#ef4444' },
        { icon: '✅',  label: 'Arrived Flights', value: kpis.arrived_flights ?? '...', color: '#065f46' },
        { icon: '🛫',  label: 'Departure Flights', value: kpis.departure_flights ?? '...', color: '#0ea5e9' },
        { icon: '🧳',  label: 'Active Carousels', value: kpis.active_carousels ?? '...', color: '#8b5cf6' },
        { icon: '⏳',  label: 'Avg Delay Duration', value: kpis.avg_delay_duration !== undefined ? `${kpis.avg_delay_duration} min` : '...', color: '#ec4899' },
        { icon: '🎯',  label: 'On-Time %', value: kpis.on_time_percentage !== undefined ? `${kpis.on_time_percentage}%` : '...', color: '#3b82f6' },
    ];

    grid.innerHTML = cards.map(c => `
        <div class="kpi-card" style="--kpi-accent:${c.color}">
            <span class="kpi-icon">${c.icon}</span>
            <div class="kpi-value" style="color:${c.color}">${c.value}</div>
            <div class="kpi-label">${c.label}</div>
        </div>
    `).join('');
}

const DELAY_REASON_FALLBACKS = [
  "Adverse weather conditions",
  "Aircraft technical inspection in progress",
  "Air traffic control slot restriction",
  "Late inbound aircraft arrival",
  "Crew availability and shift compliance",
  "Ground handling operational constraint",
  "Security screening and clearance delay",
  "Runway traffic congestion",
  "Baggage loading and reconciliation delay",
  "Operational turnaround delay"
];

function stableDelayReason(f) {
  const raw = String(f.delay_reason || "").trim();
  const badReasons = [
    "",
    "Operational review in progress",
    "Operational issue",
    "Unknown",
    "N/A",
    "null",
    "undefined"
  ];

  if (raw && !badReasons.includes(raw)) {
    return raw;
  }

  const key = String(f.flight_number || f.id || f.gate_number || "flight");
  let hash = 0;
  for (let i = 0; i < key.length; i++) {
    hash = ((hash << 5) - hash) + key.charCodeAt(i);
    hash |= 0;
  }

  return DELAY_REASON_FALLBACKS[Math.abs(hash) % DELAY_REASON_FALLBACKS.length];
}

function getAlertClass(reason, status) {
  const text = `${reason || ""} ${status || ""}`.toLowerCase();
  if (text.includes("weather")) return "alert-weather";
  if (text.includes("security")) return "alert-security";
  if (text.includes("crew")) return "alert-crew";
  if (text.includes("technical")) return "alert-technical";
  if (text.includes("air traffic") || text.includes("atc")) return "alert-atc";
  if (text.includes("ground")) return "alert-ground";
  if (text.includes("baggage")) return "alert-baggage";
  if (text.includes("runway")) return "alert-runway";
  if (text.includes("turnaround") || text.includes("operational")) return "alert-operational";
  if (status === "Boarding") return "alert-boarding";
  if (status === "Cancelled") return "alert-cancelled";
  if (status === "Arrived") return "alert-arrived";
  return "alert-operational";
}

function renderOperationalAlerts(alertsData) {
    const container = document.getElementById("operational-alerts-list");
    if (!container) return;

    if (!alertsData || alertsData.length === 0) {
        container.innerHTML = '<div class="empty-alert">No active operational alerts</div>';
        return;
    }

    const html = alertsData.map(a => {
        let buttonsHtml = '';
        
        let viewBtn = '';
        if (a.flight_id) {
            viewBtn = `<button class="ops-btn ops-btn-view" onclick="viewFlight(${a.flight_id})" title="View Flight">View Flight</button>`;
        } else {
            viewBtn = `<button class="ops-btn ops-btn-view" disabled title="No Flight Attached">View Flight</button>`;
        }

        if (a.status === 'New') {
            buttonsHtml = `
                ${viewBtn}
                <button class="ops-btn ops-btn-ack" onclick="acknowledgeAlert(event, ${a.id})" title="Acknowledge">Acknowledge</button>
                <button class="ops-btn ops-btn-res" onclick="resolveAlert(event, ${a.id})" title="Resolve">Resolve</button>
                <button class="ops-btn ops-btn-dis" onclick="dismissAlert(event, ${a.id})" title="Dismiss">Dismiss</button>
            `;
        } else if (a.status === 'Acknowledged') {
            buttonsHtml = `
                ${viewBtn}
                <button class="ops-btn ops-btn-res" onclick="resolveAlert(event, ${a.id})" title="Resolve">Resolve</button>
                <button class="ops-btn ops-btn-dis" onclick="dismissAlert(event, ${a.id})" title="Dismiss">Dismiss</button>
            `;
        }

        let alertClass = 'alert-info';
        const typeLower = (a.alert_type || '').toLowerCase();
        if (typeLower.includes('delay') || typeLower.includes('maintenance')) {
            alertClass = 'alert-warning';
        } else if (typeLower.includes('cancel')) {
            alertClass = 'alert-danger';
        } else if (typeLower.includes('gate') || typeLower.includes('carousel')) {
            alertClass = 'alert-gate-change';
        }

        const badgeClass = a.status === 'Acknowledged' ? 'ops-badge-ack' : 'ops-badge-new';
        const badgeText = a.status === 'Acknowledged' ? 'ACKNOWLEDGED' : 'NEW';

        return `
            <div class="ops-alert ${alertClass}">
                <div class="ops-alert-main">
                    <div class="ops-alert-header">
                        <span class="ops-alert-title">${a.flight_number || 'Gate Alert'}</span>
                        <span class="ops-badge ${badgeClass}">${badgeText}</span>
                    </div>
                    <div class="ops-alert-subtitle">${a.message}</div>
                </div>
                <div class="ops-alert-actions">
                    ${buttonsHtml}
                </div>
            </div>
        `;
    }).join("");

    container.innerHTML = html;
}

// ── viewFlight ─────────────────────────────────────────────────────────────
// Navigates from an operational alert directly to the matching flight row on
// the Flight Board, then scrolls to it and highlights it for 4 seconds.
async function viewFlight(flightId) {
    console.log('Opening flight:', flightId);

    if (!flightId) {
        showToast('No flight ID associated with this alert.', 'error');
        return;
    }

    // Ensure an airport context is available (analytics is HYD-only)
    if (!selectedAirport) {
        const stored = localStorage.getItem('selectedAirport');
        if (stored) {
            try { selectedAirport = JSON.parse(stored); } catch (e) { /* ignore */ }
        }
        if (!selectedAirport) {
            showToast('Please select an airport first.', 'error');
            showPage('airports');
            return;
        }
    }

    // Pre-clear all filters so the flight will be visible after renderBoard()
    activeTerminal = 'ALL';
    activeAirline = 'ALL';
    activeStatusFilter = 'ALL';
    selectedAirline = null;

    // Pre-set the correct tab (arrival / departure) if the flight is already cached
    const cached = allFlights.find(f => f.id === flightId);
    if (cached) {
        activeCategory = cached.flight_type; // 'arrival' | 'departure'
    }

    // Store the ID so renderBoard() can highlight the row once it renders
    pendingHighlightFlightId = flightId;

    // Navigate — showPage('flights') calls setupFlightPage() then fetchFlights()
    // setupFlightPage() only resets activeCategory when it is null/'info', so the
    // value we set above is preserved when the flight type was already known.
    showPage('flights');
}

async function acknowledgeAlert(event, alertId) {
    event.stopPropagation();
    console.log("Alert action:", "acknowledge", alertId);
    try {
        const res = await fetch(`${API}/alerts/${alertId}/acknowledge`, { method: 'PATCH', headers: authHeaders() });
        console.log("Response status:", res.status);
        if (!res.ok) throw new Error('Failed to acknowledge');
        showToast('Alert acknowledged', 'success');
        if (typeof loadAnalytics === 'function') {
            await loadAnalytics();
        }
    } catch (err) { showToast(err.message, 'error'); }
}

async function resolveAlert(event, alertId) {
    event.stopPropagation();
    console.log("Alert action:", "resolve", alertId);
    try {
        const res = await fetch(`${API}/alerts/${alertId}/resolve`, { method: 'PATCH', headers: authHeaders() });
        console.log("Response status:", res.status);
        if (!res.ok) throw new Error('Failed to resolve');
        showToast('Alert resolved', 'success');
        if (typeof loadAnalytics === 'function') {
            await loadAnalytics();
        }
    } catch (err) { showToast(err.message, 'error'); }
}

async function dismissAlert(event, alertId) {
    event.stopPropagation();
    console.log("Alert action:", "dismiss", alertId);
    try {
        const res = await fetch(`${API}/alerts/${alertId}/dismiss`, { method: 'PATCH', headers: authHeaders() });
        console.log("Response status:", res.status);
        if (!res.ok) throw new Error('Failed to dismiss');
        showToast('Alert dismissed', 'success');
        if (typeof loadAnalytics === 'function') {
            await loadAnalytics();
        }
    } catch (err) { showToast(err.message, 'error'); }
}

async function clearGateAlertFromFeed(event, flightId) {
    event.stopPropagation();
    try {
        const res = await fetch(`${API}/flights/${flightId}/clear-gate-alert`, {
            method: 'PATCH',
            headers: authHeaders()
        });
        if (!res.ok) throw new Error('Failed');
        // Optimistically update local data so alert vanishes immediately
        const f = allFlights.find(x => x.id === flightId);
        if (f) { f.gate_changed = false; f.previous_gate = null; }
        fetchFlights(); // Refresh feeds and dashboard state
        showToast('Gate change alert dismissed', 'success');
    } catch (err) {
        showToast('Could not clear gate alert', 'error');
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

function renderTerminalChart(data) {
    const ctx = document.getElementById('terminalChart');
    if (!ctx) return;

    // Destroy stale instance to prevent Chart.js canvas conflicts on re-render
    if (terminalChartInstance) { terminalChartInstance.destroy(); terminalChartInstance = null; }

    // Doughnut chart — clean representation of terminal occupancy distribution
    terminalChartInstance = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: data.map(d => d.terminal.startsWith("T") ? `Terminal ${d.terminal}` : d.terminal),
            datasets: [{
                data: data.map(d => d.count),
                backgroundColor: [
                    '#3b82f6', // cobalt blue
                    '#10b981', // emerald green
                    '#8b5cf6', // violet
                    '#f59e0b', // amber gold
                    '#ec4899'  // rose pink
                ],
                borderWidth: 2,
                borderColor: '#ffffff',
                hoverOffset: 4
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        boxWidth: 12,
                        padding: 16,
                        font: { size: 11, family: 'Inter, sans-serif' }
                    }
                }
            },
            cutout: '65%' // sleek premium donut cut
        }
    });
}

function renderGateInfrastructure(data) {
    const container = document.getElementById('gate-infrastructure-summary');
    if (!container) return;

    const total = data.total_gates || 0;
    const available = data.available_gates || 0;
    const occupied = data.occupied_gates || 0;
    const maintenance = data.maintenance_gates || 0;

    console.log("Gate Infrastructure API response:", data);

    const availPct = total > 0 ? Math.round((available / total) * 100) : 0;
    const occPct = total > 0 ? Math.round((occupied / total) * 100) : 0;
    const maintPct = total > 0 ? Math.round((maintenance / total) * 100) : 0;

    container.innerHTML = `
        <div style="display:flex; flex-direction:column; gap:6px;">
            <div style="display:flex; justify-content:space-between; font-size:11px; font-weight:700; color:var(--text3); text-transform:uppercase; letter-spacing:0.5px;">
                <span>🟢 Available Gates</span>
                <span>${available} / ${total} (${availPct}%)</span>
            </div>
            <div style="height:8px; width:100%; background:#e2e8f0; border-radius:4px; overflow:hidden;">
                <div style="height:100%; width:${availPct}%; background:#10b981; border-radius:4px;"></div>
            </div>
        </div>
        <div style="display:flex; flex-direction:column; gap:6px;">
            <div style="display:flex; justify-content:space-between; font-size:11px; font-weight:700; color:var(--text3); text-transform:uppercase; letter-spacing:0.5px;">
                <span>🔵 Occupied Gates</span>
                <span>${occupied} / ${total} (${occPct}%)</span>
            </div>
            <div style="height:8px; width:100%; background:#e2e8f0; border-radius:4px; overflow:hidden;">
                <div style="height:100%; width:${occPct}%; background:#3b82f6; border-radius:4px;"></div>
            </div>
        </div>
        <div style="display:flex; flex-direction:column; gap:6px;">
            <div style="display:flex; justify-content:space-between; font-size:11px; font-weight:700; color:var(--text3); text-transform:uppercase; letter-spacing:0.5px;">
                <span>🔴 Maintenance Gates</span>
                <span>${maintenance} / ${total} (${maintPct}%)</span>
            </div>
            <div style="height:8px; width:100%; background:#e2e8f0; border-radius:4px; overflow:hidden;">
                <div style="height:100%; width:${maintPct}%; background:#ef4444; border-radius:4px;"></div>
            </div>
        </div>
    `;
}

function renderTrafficChart(data) {
    if (!data) return;
    const ctx = document.getElementById('trafficChart');
    if (!ctx) return;

    if (trafficChartInstance) { trafficChartInstance.destroy(); trafficChartInstance = null; }

    const labels = data.map(d => d.interval);
    const arrivals = data.map(d => d.arrivals);
    const departures = data.map(d => d.departures);

    trafficChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Departures',
                    data: departures,
                    backgroundColor: '#3b82f6', // cobalt blue
                    borderRadius: 4,
                    borderSkipped: false
                },
                {
                    label: 'Arrivals',
                    data: arrivals,
                    backgroundColor: '#10b981', // green
                    borderRadius: 4,
                    borderSkipped: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { 
                legend: { 
                    display: true,
                    position: 'bottom',
                    labels: { font: { size: 10, family: 'Inter, sans-serif' } }
                } 
            },
            scales: {
                x: { grid: { display: false }, ticks: { font: { size: 9, family: 'Inter, sans-serif' } } },
                y: { beginAtZero: true, grid: { color: '#f1f5f9' }, ticks: { font: { size: 9 } } }
            }
        }
    });
}
function renderCarouselChart(data) {
    if (!data) return;
    const ctx = document.getElementById('carouselChart');
    if (!ctx) return;

    if (carouselChartInstance) { carouselChartInstance.destroy(); carouselChartInstance = null; }

    const labels = data.map(d => d.carousel);
    const values = data.map(d => d.assigned_flights);

    carouselChartInstance = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Assigned Flights',
                data: values,
                backgroundColor: '#8b5cf6',
                borderRadius: 4
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false }
            },
            scales: {
                x: {
                    beginAtZero: true,
                    ticks: { stepSize: 1 }
                }
            }
        }
    });
}




function renderTopDelayedFlights(flights) {
    const container = document.getElementById("top-delayed-flights-list");
    if (!container) return;

    // Filter delayed flights and sort descending by delay_minutes
    const delayed = flights.filter(f => f.status === "Delayed" && f.delay_minutes > 0)
                           .sort((a, b) => b.delay_minutes - a.delay_minutes)
                           .slice(0, 5);

    if (delayed.length === 0) {
        container.innerHTML = '<div class="empty-alert">No delayed flights</div>';
        return;
    }

    const html = delayed.map(f => `
        <div class="ops-alert ops-alert-other" style="background:#f8fafc; border-left:4px solid #ef4444; margin-bottom:8px; padding:10px 14px;">
            <div class="ops-alert-content">
                <div class="ops-alert-title" style="color:#0f172a; display:flex; justify-content:space-between; align-items:center;">
                    <span>${f.flight_number}</span>
                    <span style="color:#ef4444; font-size:13px; font-weight:700;">${f.delay_minutes} min</span>
                </div>
                <div class="ops-alert-subtitle" style="color:#64748b; font-size:12px; margin-top:2px;">
                    ${f.delay_reason || 'Operational delay'} • Gate ${f.gate_number || '—'}
                </div>
            </div>
        </div>
    `).join("");

    container.innerHTML = html;
}

function renderDelaySeveritySummary(flights) {
    const container = document.getElementById("delay-severity-summary");
    if (!container) return;

    let minor = 0;
    let moderate = 0;
    let severe = 0;

    flights.forEach(f => {
        if (f.status === "Delayed" && f.delay_minutes > 0) {
            if (f.delay_minutes <= 30) minor++;
            else if (f.delay_minutes <= 60) moderate++;
            else severe++;
        }
    });

    container.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; background:#f8fafc; padding:12px 16px; border-radius:8px; border-left:4px solid #f59e0b;">
            <span style="font-weight:600; color:#334155; font-size:13px;">Minor Delay (0-30 min)</span>
            <span style="font-weight:700; font-size:16px; color:#f59e0b;">${minor}</span>
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center; background:#f8fafc; padding:12px 16px; border-radius:8px; border-left:4px solid #f97316;">
            <span style="font-weight:600; color:#334155; font-size:13px;">Moderate Delay (31-60 min)</span>
            <span style="font-weight:700; font-size:16px; color:#f97316;">${moderate}</span>
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center; background:#fef2f2; padding:12px 16px; border-radius:8px; border-left:4px solid #ef4444;">
            <span style="font-weight:600; color:#991b1b; font-size:13px;">Severe Delay (60+ min)</span>
            <span style="font-weight:700; font-size:16px; color:#ef4444;">${severe}</span>
        </div>
    `;
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