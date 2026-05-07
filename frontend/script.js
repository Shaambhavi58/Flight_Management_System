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
    const regLink = document.getElementById('nav-register-link');
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
        if (role === 'admin') {
            actions = `
  <td class="cell-actions">
    <div class="action-container">
        <button class="action-btn btn-edit" onclick="editFlight(${f.id})">Edit</button>
        <button class="action-btn btn-delete" onclick="deleteFlight(${f.id})">Delete</button>
    </div>
  </td>`;
        }
        tr.innerHTML = `
  <td class="cell-flight">${f.flight_number}</td>
  <td class="cell-airline-info"><div class="cell-airline"><span class="airline-badge badge-${f.airline_code}">${f.airline_code}</span>${f.airline_name}</div></td>
  <td class="cell-route">${formatRoute(f.origin, f.destination)}</td>
  <td class="cell-time">${f.departure_time}</td>
  <td class="cell-time">${f.arrival_time}</td>
  <td class="cell-gate">${f.gate_number}</td>
  <td class="cell-terminal-info"><span class="terminal-badge terminal-${f.terminal_number}">${f.terminal_number}</span></td>
  <td class="cell-status"><span class="status-badge status-${f.status.replace(/\s+/g, '-')}">${f.status}</span></td>
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
        renderAlerts(data.live_alerts);               // live alert feed
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

function renderAlerts(alerts) {
    const container = document.getElementById('alerts-container');
    const badge     = document.getElementById('alerts-count-badge');
    if (!container) return;

    // Show a "no alerts" message when everything is operating normally
    if (!alerts || alerts.length === 0) {
        container.innerHTML = '<p style="color:var(--text3);font-size:13px;padding:12px 0">✅ No active alerts — all operations nominal.</p>';
        if (badge) { badge.textContent = ''; badge.classList.remove('visible'); }
        return;
    }

    // Update the alert count badge in the sidebar/header
    if (badge) {
        badge.textContent = alerts.length;   // show number of active alerts
        badge.classList.add('visible');       // make badge visible
    }

    // Render each alert with its CSS class for color coding (warning=orange, info=blue)
    container.innerHTML = alerts.map(a => `
        <div class="live-alert-item alert-${a.type}">
            ${a.message}
        </div>
    `).join('');
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