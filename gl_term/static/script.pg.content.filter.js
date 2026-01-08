'use strict';

/* ---------------- Globals from original script ---------------- */
let a_or_b = '';
let current_data;
let ptsd_name = '';
let currentRoute = '';

/* ---------------- DOM References (updated for UmbrelOS layout) ---------------- */
const mainContent = document.querySelector('.app');
if (!mainContent) throw new Error('Main content container (#mainContent or .main-content) not found');
renderNavBar()
/* ---------------- Title / Sidebar Wiring ---------------- */
function renderNavBar() {
    document.querySelector('.sdc-app').innerHTML += `<div class="sidebar"></div>`
    let sidebar = document.querySelector('.sidebar')
    sidebar.innerHTML = `
    <br><br>
    <div class="fixed top-0 left-0 h-full w-60 bg-gray-1000 p-4 flex flex-col space-y-2">
    <!-- Spacing at the top -->
    <div class="pt-6"></div>

    <!-- Close Menu Link -->
    <a 
        class="mobcap text-blue-400 hover:text-blue-200 cursor-pointer mb-4"
        onclick="document.querySelector('.sidebar').style.display = 'none'; document.querySelector('.app').style.display = 'block';"
        href="javascript:void(0)">
        Close Menu
    </a>

    <!-- Home -->
    <div 
    style="padding: 8px 8px;"
        class="flex items-center p-2 rounded hover:bg-blue-600 hover:text-white cursor-pointer"
        onclick="ChangeContentMain('Apps')">
        <i class="fa fa-home w-6"></i>
        <span class="ml-2">Home</span>
    </div>

    <!-- Ch Pass -->
    <div 
    style="padding: 8px 8px;"
        class="flex items-center p-2 rounded hover:bg-blue-600 hover:text-white cursor-pointer"
        onclick="FetchData('/apisettings/chpass')">
        <i class="fa fa-eye-slash w-6"></i>
        <span class="ml-2">Ch Pass</span>
    </div>

    <!-- Files -->
    <div 
    style="padding: 8px 8px;"
        class="flex items-center p-2 rounded hover:bg-blue-600 hover:text-white cursor-pointer"
        onclick="ChangeContentMain('Files')">
        <i class="fa fa-folder-open w-6"></i>
        <span class="ml-2">Files</span>
    </div>

    <!-- Terminal -->
    <div 
    style="padding: 8px 8px;"
        class="flex items-center p-2 rounded hover:bg-blue-600 hover:text-white cursor-pointer"
        onclick="ChangeContentMain('Terminal')">
        <i class="fa fa-terminal w-6"></i>
        <span class="ml-2">Terminal</span>
    </div>

    <!-- Logout -->
    <div 
    style="padding: 8px 8px;"
        class="flex items-center rounded hover:bg-blue-600 hover:text-white cursor-pointer"
        onclick="location.href='/logout'">
        <i class="fa fa-sign-out w-6"></i>
        <span class="ml-2">Logout</span>
    </div>
</div>`
;
}
wireUpNavItems()

function wireUpNavItems() {
    const links = Array.from(document.querySelectorAll('.sidebar-item[data-nav]'));
    links.forEach(item => {
        item.removeEventListener('click', onNavClick);
        item.addEventListener('click', onNavClick);
    });
}

function onNavClick(e) {
    const route = e.currentTarget.getAttribute('data-nav');
    if (!route) return;
    ChangeContentMain(route);
}

/* ---------------- Fetch Utilities ---------------- */
async function FetchData(url) {
    try {
        const res = await fetch(url, { credentials: 'same-origin' });
        if (!res.ok) {
            const msg = `Error ${res.status}: ${res.statusText}`;
            showToast(msg, 4000);
            return null;
        }
        const text = await res.text();
        mainContent.innerHTML = text
        return text;
    } catch (err) {
        const msg = `Fetch failed: ${err.message}`;
        showToast(msg, 4000);
        return null;
    }
}

/* ---------------- Main Content Module Loader ---------------- */
function ChangeContentMain(moduleName, path = '/index') {
    SetHrefLink(moduleName);
    FetchData(`/modules/${moduleName}${path}`)
}

/* ---------------- Settings UI Logic ---------------- */
function LoadSettingsOption(settings) {
    if (!mainContent) return;
    let routeToSet = '';
    let html = '';

    if (settings === 'main_list') {
        routeToSet = 'main_list';
        FetchData('/apisettings/lists');
    } else if (settings === 'About') {
        routeToSet = 'Settings/About';
        html = `<h2>About</h2><p>This is your GL_TERM App.</p>`;
        SetHrefLink(routeToSet);
        mainContent.innerHTML = html;
    } else {
        return LoadSettingsOption('main_list');
    }

    updateTitlebarButtons();
}

function wireUpSettingsLinks() {
    const links = Array.from(mainContent.querySelectorAll('.settings-link'));
    links.forEach(link => {
        link.removeEventListener('click', onSettingsLinkClick);
        link.addEventListener('click', onSettingsLinkClick);
    });
}

function onSettingsLinkClick(e) {
    e.preventDefault();
    const setting = e.currentTarget.dataset.setting;
    if (!setting) return;
    LoadSettingsOption(setting);
}

/* ---------------- History Management ---------------- */
function SetHrefLink(hreflink) {
    try {
        currentRoute = hreflink || '';
        const newHash = `#/${hreflink}`;
        history.pushState(null, '', newHash);
    } catch (err) {
        currentRoute = hreflink;
        console.warn('SetHrefLink warning:', err);
    }
}

window.addEventListener('popstate', () => {
    const hash = (location.hash || '').replace(/^#\//, '');
    currentRoute = hash;
});

/* ---------------- Toasts (unchanged) ---------------- */
function showToast(message, timeout = 2000) {
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.setAttribute('aria-live', 'polite');
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;
    container.appendChild(toast);
    void toast.offsetHeight; // force reflow
    toast.classList.add('show');
    if (timeout > 0) {
        setTimeout(() => removeToast(toast), timeout);
    }
    return toast;
}

function removeToast(toast) {
    if (!toast || !toast.parentElement) return;
    toast.classList.add('hide');
    toast.addEventListener('transitionend', () => {
        if (toast.parentElement) toast.remove();
    }, { once: true });
}

/* ---------------- Sidebar Open/Close ---------------- */

/* ---------------- Outside Click for Sidebar ---------------- */
/* ---------------- Initial Setup ---------------- */
renderNavBar();
// Start default route (e.g., show settings main list or your home logic):
ChangeContentMain('Apps');

document.querySelectorAll('.sidebar')[1].remove()
