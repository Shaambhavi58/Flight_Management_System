const API = window.location.origin;
const PUB = 'http://127.0.0.1:8001';

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
let refreshTimer = null;

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

    // Page-specific setup
    if (name === 'airports') loadAirports();
    if (name === 'register') { if (role !== 'admin') { showPage('airports'); return; } loadUsers(); loadRegisterAirports(); }
    if (name === 'flights') {
        if (!selectedAirport) { showPage('airports'); return; }
        setupFlightPage();
        fetchFlights();
        refreshTimer = setInterval(fetchFlights, 5000);
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
    const regLink = document.getElementById('nav-register-link');
    if (role === 'admin') {
        regLink.classList.remove('hidden');
    } else {
        regLink.classList.add('hidden');
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
        airports.forEach(a => {
            const card = document.createElement('div');
            card.className = 'airport-card';
            card.innerHTML = `
<div class="airport-card-img">${AIRPORT_ICONS[a.code] || '✈️'}</div>
<div class="airport-card-body">
  <span class="airport-code-badge">${a.code}</span>
  <h3>${a.name}</h3>
  <p>${a.city}</p>
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
        users.forEach(u => {
            const isAdminSelf = u.username === localStorage.getItem('username');
            const menuItems = isAdminSelf
                ? `<div onclick="editUser(${u.id})"> Edit Profile</div>
                   <div onclick="resetPassword(${u.id},'${u.username}')"> Reset Password</div>`
                : `<div onclick="editUser(${u.id})"> Edit</div>
                   <div onclick="resetPassword(${u.id},'${u.username}')"> Reset Password</div>
                   <div onclick="deactivateUser(${u.id},'${u.username}')"> Deactivate</div>
                   <div class="danger" onclick="deleteUser(${u.id},'${u.username}')"> Delete</div>`;

            const tr = document.createElement('tr');
            tr.innerHTML = `
<td>${u.full_name}</td>
<td style="font-family:var(--mono);color:var(--cyan)">${u.username}</td>
<td>${u.email}</td>
<td><span class="role-badge role-${u.role}">${u.role}</span></td>
<td style="font-family:var(--mono);color:var(--text3);font-size:12px">${u.airport_id ? 'Airport #' + u.airport_id : '<em>All Airports</em>'}</td>
<td>
  <div class="user-action-dropdown">
    <button class="user-action-btn" onclick="toggleUserMenu(event,${u.id})">Actions ▾</button>
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

async function editUser(userId) {
    const newName = prompt('Enter new full name (leave blank to skip):');
    const newRole = prompt('Enter new role (admin/staff/viewer, leave blank to skip):');
    if (!newName && !newRole) return;

    const payload = {};
    if (newName && newName.trim()) payload.full_name = newName.trim();
    if (newRole && newRole.trim()) payload.role = newRole.trim();

    try {
        const res = await fetch(`${API}/auth/users/${userId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', ...authHeaders() },
            body: JSON.stringify(payload),
        });
        if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Update failed'); }
        showToast('User updated', 'success');
        loadUsers();
    } catch (err) { showToast(err.message, 'error'); }
}

async function resetPassword(userId, username) {
    if (!confirm(`Reset password for "${username}"? A new password will be sent to their email.`)) return;
    try {
        const res = await fetch(`${API}/auth/users/${userId}/reset-password`, {
            method: 'PUT',
            headers: authHeaders(),
        });
        if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Reset failed'); }
        showToast(`Password reset for ${username}`, 'success');
    } catch (err) { showToast(err.message, 'error'); }
}

async function deactivateUser(userId, username) {
    if (!confirm(`Deactivate account for "${username}"?`)) return;
    try {
        const res = await fetch(`${API}/auth/users/${userId}/deactivate`, {
            method: 'PUT',
            headers: authHeaders(),
        });
        if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Deactivate failed'); }
        showToast(`${username} deactivated`, 'success');
        loadUsers();
    } catch (err) { showToast(err.message, 'error'); }
}

async function deleteUser(userId, username) {
    if (!confirm(`Permanently delete user "${username}"? This cannot be undone.`)) return;
    try {
        const res = await fetch(`${API}/auth/users/${userId}`, {
            method: 'DELETE',
            headers: authHeaders(),
        });
        if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Delete failed'); }
        showToast(`${username} deleted`, 'success');
        loadUsers();
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
    document.querySelectorAll('.category-card').forEach(c => c.classList.remove('active'));
    const activeCatEl = document.querySelector(`[data-type="${activeCategory}"]`);
    if (activeCatEl) activeCatEl.classList.add('active');
    document.getElementById('flight-board-section').classList.remove('hidden');
    document.getElementById('airline-info-section').classList.add('hidden');
    document.querySelectorAll('.tab-btn').forEach((b, i) => b.classList.toggle('active', i === 0));
    document.getElementById('airline-filter').value = 'ALL';
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
        if (activeCategory !== 'info') renderBoard();
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

    // Update statistics dashboard before any further filtering
    document.getElementById('stat-total').textContent = filtered.length;
    document.getElementById('stat-arrived').textContent = filtered.filter(f => f.status === 'Arrived').length;
    document.getElementById('stat-boarding').textContent = filtered.filter(f => f.status === 'Boarding').length;
    document.getElementById('stat-scheduled').textContent = filtered.filter(f => f.status === 'Scheduled').length;
    document.getElementById('stat-delayed').textContent = filtered.filter(f => f.status === 'Delayed').length;

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

    tbody.innerHTML = '';
    filtered.forEach(f => {
        const tr = document.createElement('tr');
        let actions = '';
        if (role === 'admin') {
            actions = `
            <td>
                <button class="action-btn" onclick="editFlight(${f.id})">Edit</button>
                <button class="action-btn btn-delete" onclick="deleteFlight(${f.id})">Delete</button>
            </td>`;
        }
        tr.innerHTML = `
  <td class="cell-flight">${f.flight_number}</td>
  <td><div class="cell-airline"><span class="airline-badge badge-${f.airline_code}">${f.airline_code}</span>${f.airline_name}</div></td>
  <td>${f.origin} &rarr; ${f.destination}</td>
  <td class="cell-time">${f.departure_time}</td>
  <td class="cell-time">${f.arrival_time}</td>
  <td class="cell-gate">${f.gate_number}</td>
  <td class="cell-terminal terminal-${f.terminal_number}">${f.terminal_number}</td>
  <td><span class="status-badge status-${f.status}">${f.status}</span></td>
  ${role === 'admin' ? actions : ''}`;
        tbody.appendChild(tr);
    });
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
    const status = prompt("Enter new status:");
    if (!status) return;

    try {
        const res = await fetch(`${API}/flights/${id}`, {
            method: "PUT",
            headers: {
                "Content-Type": "application/json",
                ...authHeaders()
            },
            body: JSON.stringify({ status })
        });

        if (!res.ok) throw new Error("Update failed");

        showToast("Flight updated", "success");
        fetchFlights();
    } catch (err) {
        showToast(err.message, "error");
    }
}

async function syncLiveFlights() {
    try {
        const res = await fetch(`${PUB}/publish`, { method: 'POST' });
        if (res.ok) {
            showToast('Live flights syncing via RabbitMQ...', 'success');
            setTimeout(fetchFlights, 3000);
        } else {
            showToast('Publisher not available on port 8001', 'error');
        }
    } catch (err) {
        showToast('Start flight_publisher on port 8001 first', 'error');
    }
}

// ── Helpers ───────────────────────────────────────────────────────
function authHeaders() {
    return token ? { 'Authorization': `Bearer ${token}` } : {};
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