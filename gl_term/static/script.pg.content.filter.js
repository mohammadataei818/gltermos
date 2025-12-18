let a_or_b = "";
let current_data;
let ptsd_name = "";

/* ---------------- Dock Buttons ---------------- */

const dabdab = `
<a class="fl-r ct-bar" href="/" onclick="window.location.href = '/' ">
  <img width="75" src="/static/data/home.png"/>
</a>
<a class="fl-r ct-bar" href="/settings" onclick="indow.location.href = '/settings'">
  <img width="75" src="/static/data/settings.png"/>
</a>
<a class="fl-r ct-bar" href="/logout" onclick="indow.location.href = '/logout'">
  <img width="75" src="/static/data/logout.png"/>
</a>
`;

/* ---------------- Flash Messages ---------------- */

setTimeout(() => {
    const fm = document.getElementById("flashed-messages");
    if (fm) fm.remove();
}, 2000);

/* ---------------- Main Content ---------------- */

function ChangeContentMain(aasd,damdam = "/index") {
    const topSlot = document.querySelector(".top-slot-profile");
    const controlDock = document.querySelector(".control-dock");

    if (!topSlot || !controlDock) return;

    if (aasd === "appx_list") {
        topSlot.innerHTML = "";
        controlDock.innerHTML = dabdab;
        SetHrefLink("Apps");
    } else {
        SetHrefLink(aasd);

        topSlot.innerHTML = `
<div class="window-bar">
    <a class="btn-a pd-sm fl-r" href="#/Apps" onclick="ChangeContentMain('appx_list'); return false;">X</a>
    <span> ${aasd}</span>
</div>`;

        controlDock.innerHTML = "";
    }

    FetchData(`/modules/${aasd}${damdam}`);
}

/* ---------------- Home Screen ---------------- */

if (win_mode === "WinMode.HomeScreen") {
    document.querySelector(".app").innerHTML = `
<div class="navbar"><div class="control-dock"></div></div>
<div class="top-slot-profile"></div>
<div id="pg-content-m"></div>
`;
    document.querySelector(".control-dock").innerHTML = dabdab;
    ChangeContentMain("appx_list");
}

/* ---------------- Settings Page ---------------- */

if (win_mode === "WinMode.SettingsPage") {
    document.querySelector(".app").innerHTML = `
<div class="navbar"><div class="control-dock"></div></div>
<div class="hbtncontainer">
  <button onclick="LoadSettingsOption('main_list')" class="hdbtn btn-a">Back</button>
</div>
<div class="top-slot-profile"></div>
<div id="pg-content-m"></div>
`;

    document.querySelector(".control-dock").innerHTML = dabdab;
    LoadSettingsOption("main_list");
}
if (win_mode === "WinMode.SettingsPage") {
    console.log('Are You Excepting Something?')
}
/* ---------------- Settings ---------------- */

function LoadSettingsOption(settings) {
    let setiscmd = "";
    let enableSettingsBackButton = true;

    if (settings === "main_list") {
        SetHrefLink("Settings");
        enableSettingsBackButton = false;
        setiscmd = `
<br>
<a href="javascript:" onclick="LoadSettingsOption('wlch')">Wallpaper Changer</a><br>
<a href="javascript:" onclick="LoadSettingsOption('About')">About</a>
`;
    }

    if (settings === "About") {
        SetHrefLink("Settings/About");
        setiscmd = `
<h2>About This Program</h2>
<p>WinSrvOS (GL_TERM) v1</p>
`;
    }

    if (settings === "wlch") {
        SetHrefLink("Settings/wlch");
        FetchData("/apisettings/wlch");
        return;
    }

    document.getElementById("pg-content-m").innerHTML = setiscmd;

    const backBtn = document.querySelector(".hdbtn");
    if (backBtn) {
        backBtn.style.display = enableSettingsBackButton ? "" : "none";
    }
}

/* ---------------- Utilities ---------------- */

async function FetchData(url) {
    const res = await fetch(url);
    const text = await res.text();
    document.getElementById("pg-content-m").innerHTML = text;
}

function SetHrefLink(hreflink) {
    const a = document.createElement("a");
    a.href = `#/${hreflink}`;
    document.body.appendChild(a);
    a.click();
    a.remove();
}

// time for the toast
function showToast(message, timeout = 2000) {
    const toastContainer = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = 'toast';
    toast.textContent = message;

    toastContainer.appendChild(toast);

    // Trigger reflow to enable animation
    toast.offsetHeight;

    toast.classList.add('show');

    if (timeout > 0) {
        setTimeout(() => {
            removeToast(toast);
        }, timeout);
    }

    return toast;
}

function updateToastMessage(toast, message) {
    if (!toast) {
        return;
    }
    toast.textContent = message;
}

async function removeToast(toast) {
    if (!toast) {
        return;
    }
    toast.classList.add('hide');
    toast.addEventListener('transitionend', () => {
        toast.remove();
    });
}
