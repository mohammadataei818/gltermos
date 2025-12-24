'use strict';

/* global win_mode */ // optional external signal

let a_or_b = '';
let current_data;
let ptsd_name = '';

// track the current logical route (string like "sys1$appx_list", "main_list", "Settings/About", "wlch", etc.)
let currentRoute = '';

/* ---------------- Base App Layout ---------------- */

const appRoot = document.querySelector('.app');
if (!appRoot) throw new Error('App root (.app) not found');

function renderBaseLayout() {
  appRoot.innerHTML = `
    <div id="navbar" class="navbar sidenav" role="navigation" aria-hidden="true">
      <button id="nav-close-btn" class="closebtn" title="Close navigation" aria-label="Close navigation">×</button>
      <a href="/" data-nav="/">Home</a>
      <a href="/settings" data-nav="/settings">Settings</a>
      <a href="javascript:void(0)" onclick="ChangeContentMain('sys1$terminal')">Shell</a>
      <a href="/logout" data-nav="/logout">Logout</a>
      <div class="control-dock"></div>
    </div>

    <div id="main">
      <div class="top-slot-profile"></div>
      <div id="pg-content-m"></div>
      <div id="toast-container" aria-live="polite"></div>
    </div>
  `;
}

/* initial render */
renderBaseLayout();

/* ---------------- Titlebar (HOME only, left-aligned) ---------------- */

/*
  Design:
   - window-bar is a flex container: left group and right area
   - leftGroup contains the hamburger (nav-open) and HOME (⌂)
   - HOME is hidden when currentRoute is a "main app" (sys1$appx_list, main_list)
   - Back button is intentionally removed
*/
function wireUpTitlebar() {
  const topSlot = document.querySelector('.top-slot-profile');
  if (!topSlot) return;

  // ensure window-bar exists and set layout styles to avoid center alignment
  let wb = topSlot.querySelector('.window-bar');
  if (!wb) {
    wb = document.createElement('div');
    wb.className = 'window-bar';
    // minimal inline layout to ensure left alignment regardless of external CSS
    wb.style.display = 'flex';
    wb.style.alignItems = 'center';
    wb.style.justifyContent = 'space-between';
    wb.style.gap = '0.5rem';
    topSlot.appendChild(wb);
  } else {
    // make sure layout properties are present if some external CSS removed them
    if (!wb.style.display) wb.style.display = 'flex';
    wb.style.alignItems = 'center';
    wb.style.justifyContent = 'space-between';
  }

  // LEFT GROUP: contains hamburger + home
  let leftGroup = wb.querySelector('.title-left-group');
  if (!leftGroup) {
    leftGroup = document.createElement('div');
    leftGroup.className = 'title-left-group';
    leftGroup.style.display = 'flex';
    leftGroup.style.alignItems = 'center';
    leftGroup.style.justifyContent = 'flex-start';
    leftGroup.style.gap = '0.4rem';
    wb.insertBefore(leftGroup, wb.firstChild);
  } else {
    leftGroup.style.display = 'flex';
    leftGroup.style.alignItems = 'center';
    leftGroup.style.justifyContent = 'flex-start';
    leftGroup.style.gap = '0.4rem';
  }

  // NAV-HAMBURGER (☰) — left-most toggle for the sidebar
  let openBtn = leftGroup.querySelector('#nav-open-btn');
  if (!openBtn) {
    openBtn = document.createElement('button');
    openBtn.id = 'nav-open-btn';
    openBtn.className = 'btn-a pd-sm fl-r';
    openBtn.type = 'button';
    openBtn.textContent = '☰';
    openBtn.setAttribute('aria-label', 'Open navigation');
    // minimal reset to avoid inherited centering
    openBtn.style.margin = '0';
    leftGroup.appendChild(openBtn);
  } else {
    openBtn.style.margin = '0';
  }

  // HOME BUTTON (⌂) — to the right of the hamburger in the left group
  let homeBtn = leftGroup.querySelector('#title-home-btn');
  if (!homeBtn) {
    homeBtn = document.createElement('button');
    homeBtn.id = 'title-home-btn';
    homeBtn.className = 'btn-a title-btn';
    homeBtn.type = 'button';
    homeBtn.textContent = '⌂';
    homeBtn.title = 'Home';
    homeBtn.setAttribute('aria-label', 'Home');
    // prevent centering from inherited CSS
    homeBtn.style.margin = '0';
    homeBtn.style.alignSelf = 'center';
    leftGroup.appendChild(homeBtn);

    homeBtn.addEventListener('click', (e) => {
      e.preventDefault();
      ChangeContentMain('sys1$appx_list');
    });
  } else {
    homeBtn.textContent = '⌂';
    homeBtn.title = 'Home';
    homeBtn.setAttribute('aria-label', 'Home');
    homeBtn.style.margin = '0';
    homeBtn.style.alignSelf = 'center';
  }

  // RIGHT AREA: any title-right content
  let rightSpan = wb.querySelector('#of-the-ptsd');
  if (!rightSpan) {
    rightSpan = document.createElement('span');
    rightSpan.id = 'of-the-ptsd';
    rightSpan.className = 'title-right';
    // push it to the far right
    rightSpan.style.marginLeft = 'auto';
    wb.appendChild(rightSpan);
  } else {
    rightSpan.style.marginLeft = 'auto';
  }

  // wire nav open handler (ensure no duplicate handlers)
  openBtn.removeEventListener('click', open_nav);
  openBtn.addEventListener('click', open_nav);
}

/* update the visibility of the HOME button based on currentRoute */
function updateTitlebarButtons() {
  const homeBtn = document.getElementById('title-home-btn');

  // Normalize route string
  const route = (currentRoute || '').toString();

  // Main apps -> hide home
  const MAIN_APPS = new Set(['sys1$appx_list', 'main_list']);
  const showHome = !MAIN_APPS.has(route);

  if (homeBtn) {
    homeBtn.style.display = showHome ? '' : 'none';
  }
}

/* ---------------- Navigation wiring (no inline onclick in DOM) ---------------- */

function wireNavLinkClicks() {
  const navLinks = Array.from(document.querySelectorAll('#navbar a[data-nav]'));
  navLinks.forEach((lnk) => {
    lnk.removeEventListener('click', onNavLinkClick);
    lnk.addEventListener('click', onNavLinkClick);
  });
}

function onNavLinkClick(e) {
  e.preventDefault();
  const href = e.currentTarget.getAttribute('data-nav') || e.currentTarget.getAttribute('href');
  if (!href) return;

  if (href === '/' || href === '/index') {
    ChangeContentMain('sys1$appx_list');
    close_nav();
    return;
  }

  if (href === '/settings') {
    LoadSettingsOption('main_list', { fromNav: true });
    close_nav();
    return;
  }

  // default: navigate away
  window.location.href = href;
}

/* ---------------- Top-slot wiring (titlebar + nav open/close) ---------------- */

function wireUpTopSlot() {
  const topSlot = document.querySelector('.top-slot-profile');
  if (!topSlot) return;

  // ensure titlebar is wired
  wireUpTitlebar();

  // ensure nav open button exists and is wired (wireUpTitlebar already created it inside leftGroup)
  const wb = topSlot.querySelector('.window-bar');
  if (!wb) return;

  const openBtn = wb.querySelector('#nav-open-btn');
  if (openBtn) {
    openBtn.removeEventListener('click', open_nav);
    openBtn.addEventListener('click', open_nav);
  }

  // ensure close button in navbar is wired
  const closeBtn = document.getElementById('nav-close-btn');
  if (closeBtn) {
    closeBtn.removeEventListener('click', close_nav);
    closeBtn.addEventListener('click', close_nav);
  }
}

/* ---------------- Settings (keep inside main content) ---------------- */

function ensureSettingsBackButtonContainer() {
  // maintain hbtncontainer for compatibility
  const main = document.getElementById('main');
  if (!main) return null;
  let container = main.querySelector('.hbtncontainer');
  if (!container) {
    container = document.createElement('div');
    container.className = 'hbtncontainer';
    main.insertBefore(container, main.firstChild);
  }
  return container;
}

/* ---------------- Fetch utilities & routing ---------------- */

async function FetchData(url) {
  const output = document.getElementById('pg-content-m');
  try {
    const res = await fetch(url, { credentials: 'same-origin' });
    if (!res.ok) {
      const msg = `Error ${res.status}: ${res.statusText}`;
      if (output) output.innerHTML = `<pre>${msg}</pre>`;
      showToast(msg, 4000);
      return null;
    }
    const text = await res.text();
    if (output) output.innerHTML = text;
    close_nav()
    return text;
  } catch (err) {
    const msg = `Fetch failed: ${err.message}`;
    if (output) output.innerHTML = `<pre>${msg}</pre>`;
    showToast(msg, 4000);
    return null;
  }
}

/* ChangeContentMain updates history and fetches module content.
   moduleName should generally be the logical route name, e.g. 'sys1$appx_list'. */
function ChangeContentMain(moduleName, path = '/index') {
  // ensure we represent the app's logical route by moduleName
  SetHrefLink(moduleName);
  // fetch module content into main content area
  FetchData(`/modules/${moduleName}${path}`).then(() => {
    // after content load, update titlebar buttons (route already set by SetHrefLink)
    updateTitlebarButtons();
  });
}

/* ---------------- Settings UI injection ---------------- */

function LoadSettingsOption(settings, options = {}) {
  const pg = document.getElementById('pg-content-m');
  if (!pg) return;

  let html = '';
  let routeToSet = ''; // what we set as currentRoute

  if (settings === 'main_list') {
    // Represent the settings main listing by 'main_list' so the titlebar treats it as a main app
    routeToSet = 'main_list';
    FetchData('/apisettings/lists')
  } else if (settings === 'About') {
    routeToSet = 'Settings/About';
    html = `
      <div class="settings-about">
        <h2>About This Program</h2>
        <p>WinSrvOS (GL_TERM) v1</p>
      </div>
    `;
  } else if (settings === 'wlch') {
    routeToSet = 'Settings/wlch';
    // fetch server-provided settings UI into the page
    SetHrefLink(routeToSet);
    FetchData('/apisettings/wlch');
    updateTitlebarButtons();
    return;
  } else if (settings === 'Password') {
    routeToSet = 'Settings/chpass';
    // fetch server-provided settings UI into the page
    SetHrefLink(routeToSet);
    FetchData('/apisettings/chpass');
    updateTitlebarButtons();
    return;
  } else {
    // fallback to main_list
    return LoadSettingsOption('main_list', options);
  }

  // set route and inject
  SetHrefLink(routeToSet);
  pg.innerHTML = html;

  // wire links in settings content
  wireUpSettingsLinks();

  // ensure the hbtncontainer exists for compatibility
  ensureSettingsBackButtonContainer();

  // update titlebar visibility
  updateTitlebarButtons();
}

/* settings internal wiring */
function wireUpSettingsLinks() {
  const links = Array.from(document.querySelectorAll('#pg-content-m .settings-link'));
  links.forEach((lnk) => {
    lnk.removeEventListener('click', onSettingsLinkClick);
    lnk.addEventListener('click', onSettingsLinkClick);
  });
}

function onSettingsLinkClick(e) {
  e.preventDefault();
  const setting = e.currentTarget && e.currentTarget.dataset && e.currentTarget.dataset.setting;
  if (!setting) return;
  LoadSettingsOption(setting);
}

/* ---------------- History / Hash management ---------------- */

function SetHrefLink(hreflink) {
  try {
    // store route string in currentRoute for titlebar logic
    currentRoute = hreflink || '';
    // push URL hash for browser navigation
    const newHash = `#/${hreflink}`;
    // Use pushState to update URL cleanly (avoid creating extra hash navigation)
    history.pushState(null, '', newHash);
    // update titlebar buttons (immediate)
    updateTitlebarButtons();
  } catch (err) {
    // fallback: set currentRoute and update UI
    currentRoute = hreflink || '';
    updateTitlebarButtons();
    console.warn('SetHrefLink warning:', err);
  }
}

/* react to user-driven history navigation (back/forward) */
window.addEventListener('popstate', () => {
  // attempt to parse route from location.hash (format '#/route')
  const hash = (location.hash || '').replace(/^#\//, '');
  currentRoute = hash || '';
  updateTitlebarButtons();
});

/* ---------------- Toasts ---------------- */

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

  // force reflow to allow CSS transitions if present
  void toast.offsetHeight;
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
  setTimeout(() => {
    if (toast.parentElement) toast.remove();
  }, 600);
}

/* ---------------- Nav open/close globals ---------------- */

function open_nav() {
  const navbar = document.getElementById('navbar');
  const main = document.getElementById('main');
  if (!navbar || !main) return;
  navbar.style.width = '250px';
  navbar.setAttribute('aria-hidden', 'false');
  main.style.marginLeft = '250px';
  document.body.style.backgroundColor = 'rgba(0,0,0,0.4)';
}

function close_nav() {
  const navbar = document.getElementById('navbar');
  const main = document.getElementById('main');
  if (!navbar || !main) return;
  navbar.style.width = '0';
  navbar.setAttribute('aria-hidden', 'true');
  main.style.marginLeft = '0';
  document.body.style.backgroundColor = '';
}

window.open_nav = open_nav;
window.close_nav = close_nav;

/* ---------------- Outside-click & ESC handlers ---------------- */

function handleOutsideNavClick(e) {
  const navbar = document.getElementById('navbar');
  if (!navbar) return;
  const isOpen = navbar.style.width && navbar.style.width !== '0' && navbar.style.width !== '0px';
  if (!isOpen) return;
  const openBtn = document.getElementById('nav-open-btn');
  if (navbar.contains(e.target) || (openBtn && openBtn.contains(e.target))) return;
  close_nav();
}

document.removeEventListener('pointerdown', handleOutsideNavClick);
document.addEventListener('pointerdown', handleOutsideNavClick);

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') close_nav();
});

/* ---------------- Initial wiring & startup (start at HOME) ---------------- */

wireUpTopSlot();
wireNavLinkClicks();

// Start at Home (sys1$appx_list). This will set currentRoute and update titlebar.
ChangeContentMain('sys1$appx_list');
