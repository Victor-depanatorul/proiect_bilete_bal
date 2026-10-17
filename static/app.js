// ==========================================
// GESTIUNE SESIUNE ȘI NAVIGAȚIE
// (sesiunea trăiește pe server; aici doar întrebăm /api/me cine e logat)
// ==========================================

async function updateNav() {
    let user = null;
    try {
        const req = await fetch('/api/me');
        user = (await req.json()).user;
    } catch (err) {
        console.error(err);
    }

    const btnLogin = document.getElementById('btn-login');
    const btnRegister = document.getElementById('btn-register');
    const btnLogout = document.getElementById('btn-logout');
    const btnAdmin = document.getElementById('btn-admin');

    if (user) {
        if (btnLogin) btnLogin.classList.add('hidden');
        if (btnRegister) btnRegister.classList.add('hidden');
        if (btnLogout) btnLogout.classList.remove('hidden');
        if (btnAdmin && user.este_admin === 1) btnAdmin.classList.remove('hidden');
    } else {
        if (btnLogin) btnLogin.classList.remove('hidden');
        if (btnRegister) btnRegister.classList.remove('hidden');
        if (btnLogout) btnLogout.classList.add('hidden');
        if (btnAdmin) btnAdmin.classList.add('hidden');
    }
}

async function logout() {
    await fetch('/api/logout', { method: 'POST' });
    window.location.href = '/';
}

document.addEventListener('DOMContentLoaded', () => {
    updateNav();
    initPaginaBilete();
});


// ==========================================
// AUTENTIFICARE (SIGN IN / SIGN UP)
// ==========================================

async function handleLogin(e) {
    e.preventDefault();

    const email = document.getElementById('loginEmail').value;
    const parola = document.getElementById('loginPass').value;

    try {
        const req = await fetch('/api/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, parola })
        });
        const res = await req.json();

        if (req.ok) {
            alert('Te-ai autentificat cu succes!');
            window.location.href = '/';
        } else {
            alert(res.eroare || 'Date de logare incorecte.');
        }
    } catch (err) {
        console.error("Eroare la request-ul de login:", err);
        alert("Eroare de conexiune cu serverul.");
    }
}

async function handleSignup(e) {
    e.preventDefault();

    const nume = document.getElementById('signName').value;
    const email = document.getElementById('signEmail').value;
    const parola = document.getElementById('signPass').value;

    try {
        const req = await fetch('/api/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nume, email, parola })
        });
        const res = await req.json();

        if (req.ok) {
            alert('Cont creat cu succes! Te rugăm să te loghezi.');
            window.location.href = '/signin';
        } else {
            alert(res.eroare || 'Eroare la crearea contului.');
        }
    } catch (err) {
        console.error("Eroare la request-ul de inregistrare:", err);
    }
}


// ==========================================
// BILETE ȘI PLATĂ
// ==========================================

async function cumpara(tip) {
    try {
        const req = await fetch('/api/checkout', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ tip })
        });

        if (req.status === 401) {
            alert('Trebuie să fii logat ca să cumperi un bilet.');
            window.location.href = '/signin';
            return;
        }

        const res = await req.json();
        if (req.ok && res.url) {
            window.location.href = res.url; // pagina de plată Stripe
        } else {
            alert(res.eroare || 'Eroare la inițierea plății.');
        }
    } catch (err) {
        console.error(err);
        alert('Eroare de conexiune cu serverul.');
    }
}

async function incarcaBilete() {
    const container = document.getElementById('biletele');
    if (!container) return 0;

    const req = await fetch('/api/bilete-mele');
    if (req.status === 401) {
        container.innerHTML = "<p>Loghează-te ca să îți vezi biletele.</p>";
        return 0;
    }

    const bilete = await req.json();
    if (bilete.length === 0) {
        container.innerHTML = "<p>Nu ai niciun bilet încă.</p>";
        return 0;
    }

    container.innerHTML = '';
    for (const b of bilete) {
        const card = document.createElement('div');
        card.className = 'admin-card';

        const titlu = document.createElement('h3');
        titlu.textContent = 'Bilet ' + b.tip;

        const cod = document.createElement('p');
        cod.style.wordBreak = 'break-all';
        cod.textContent = b.uuid;

        const stare = document.createElement('p');
        stare.textContent = b.validat ? 'Folosit' : 'Valid';
        stare.style.color = b.validat ? 'orange' : 'green';

        card.append(titlu, cod, stare);
        container.appendChild(card);
    }
    return bilete.length;
}

async function initPaginaBilete() {
    if (!document.getElementById('biletele')) return; // nu suntem pe /bilete

    const params = new URLSearchParams(window.location.search);
    const mesaj = document.getElementById('mesajPlata');

    if (params.get('plata') === 'anulat') {
        mesaj.textContent = 'Plata a fost anulată. Nu ai fost taxat.';
    }

    const initial = await incarcaBilete();

    // După plată, webhook-ul poate ajunge cu o mică întârziere: reîncercăm câteva secunde
    if (params.get('plata') === 'succes') {
        mesaj.textContent = 'Plata a fost primită. Se emite biletul...';
        for (let i = 0; i < 10; i++) {
            await new Promise(r => setTimeout(r, 2000));
            const acum = await incarcaBilete();
            if (acum > initial) {
                mesaj.textContent = 'Biletul tău a fost emis!';
                return;
            }
        }
        mesaj.textContent = 'Plata e confirmată, dar biletul încă nu a apărut. Reîncarcă pagina în câteva secunde.';
    }
}


// ==========================================
// FUNCȚII PENTRU PANOUL DE ADMINISTRATOR
// ==========================================

async function cautaUtilizator() {
    const query = document.getElementById('searchUser').value;
    const div = document.getElementById('rezultatUser');
    div.innerHTML = "Se caută...";

    try {
        const req = await fetch(`/api/admin/users?q=${encodeURIComponent(query)}`);
        const data = await req.json();
        div.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
    } catch (err) {
        div.innerHTML = "<span style='color:red;'>Eroare rețea.</span>";
    }
}

async function cautaTranzactie() {
    const query = document.getElementById('searchTx').value;
    const div = document.getElementById('rezultatTx');
    div.innerHTML = "Se caută...";

    try {
        const req = await fetch(`/api/admin/transactions?q=${encodeURIComponent(query)}`);
        const data = await req.json();
        div.innerHTML = `<pre>${JSON.stringify(data, null, 2)}</pre>`;
    } catch (err) {
        div.innerHTML = "<span style='color:red;'>Eroare rețea.</span>";
    }
}

async function valideazaBilet() {
    const uuid = document.getElementById('uuidBilet').value;
    const msg = document.getElementById('mesajValidare');
    msg.innerText = "Se validează...";
    msg.style.color = "black";

    try {
        const req = await fetch('/api/admin/validate-ticket', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ uuid })
        });
        const res = await req.json();

        if (req.ok) {
            msg.style.color = "green";
            msg.innerText = "Bilet valid! Acces permis.";
        } else if (res.deja_folosit) {
            msg.style.color = "orange";
            msg.innerText = "ATENȚIE: Acest bilet a fost deja scanat/folosit!";
        } else {
            msg.style.color = "red";
            msg.innerText = "Bilet invalid sau inexistent.";
        }
    } catch (err) {
        msg.style.color = "red";
        msg.innerText = "Eroare de conexiune cu serverul.";
        console.error(err);
    }
}

async function adaugaBilet() {
    const email = document.getElementById('newTicketEmail').value;
    const tip = document.getElementById('newTicketType').value;

    if (!email) {
        alert("Introdu un email valid!");
        return;
    }

    try {
        const req = await fetch('/api/admin/add-ticket', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, tip })
        });

        if (req.ok) {
            alert("Bilet emis cu succes pentru " + email);
            document.getElementById('newTicketEmail').value = '';
        } else {
            const res = await req.json();
            alert(res.eroare || "Eroare la emiterea biletului.");
        }
    } catch (err) {
        console.error(err);
        alert("Eroare de conexiune.");
    }
}