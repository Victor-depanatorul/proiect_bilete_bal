// ==========================================
// GESTIUNE SESIUNE ȘI NAVIGAȚIE
// ==========================================

async function updateNav() {
    let user = null;
    try {
        const r = await fetch('/api/me');
        if (r.ok) {
            user = (await r.json()).user;
        }
    } catch (e) {
        console.error("Eroare verificare sesiune", e);
    }

    const btnLogin = document.getElementById('btn-login');
    const btnRegister = document.getElementById('btn-register');
    const btnLogout = document.getElementById('btn-logout');
    const btnAdmin = document.getElementById('btn-admin');

    if (user) {
        if(btnLogin) btnLogin.classList.add('hidden');
        if(btnRegister) btnRegister.classList.add('hidden');
        if(btnLogout) btnLogout.classList.remove('hidden');

        if (btnAdmin && (user.este_admin === 1 || user.este_admin === true)) {
            btnAdmin.classList.remove('hidden');
        }
    } else {
        if(btnLogin) btnLogin.classList.remove('hidden');
        if(btnRegister) btnRegister.classList.remove('hidden');
        if(btnLogout) btnLogout.classList.add('hidden');
        if(btnAdmin) btnAdmin.classList.add('hidden');
    }
}

async function logout() {
    try {
        await fetch('/api/logout', { method: 'POST' });
    } catch (e) {}
    window.location.href = '/';
}

document.addEventListener('DOMContentLoaded', updateNav);

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
            window.location.href = '/';
        } else {
            if (res.necesita_verificare) {
                // REDIRECȚIONARE CĂTRE VERIFY
                window.location.href = '/verify';
            } else {
                alert(res.eroare || 'Date de logare incorecte.');
            }
        }
    } catch (err) {
        alert("Eroare de conexiune cu serverul.");
    }
}

async function handleSignup(e) {
    e.preventDefault();
    const nume = document.getElementById('signName').value;
    const email = document.getElementById('signEmail').value;
    const parola = document.getElementById('signPass').value;
    const parolaConfirm = document.getElementById('signPassConfirm').value; // Preluăm a doua parolă
    const errorDiv = document.getElementById('signupError');

    if (errorDiv) {
        errorDiv.classList.add('hidden');
        errorDiv.innerText = '';
    }

    // NOU: Verificăm dacă parolele coincid
    if (parola !== parolaConfirm) {
        if (errorDiv) {
            errorDiv.innerText = 'Parolele nu coincid!';
            errorDiv.classList.remove('hidden');
        } else {
            alert('Parolele nu coincid!');
        }
        return; // Oprim execuția, nu mai trimitem datele la server
    }

    try {
        const req = await fetch('/api/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ nume, email, parola })
        });
        const res = await req.json();

        if (req.ok) {
            // REDIRECȚIONARE CĂTRE VERIFY
            window.location.href = '/verify';
        } else {
            if (errorDiv) {
                errorDiv.innerText = res.eroare || 'Eroare la crearea contului.';
                errorDiv.classList.remove('hidden');
            } else {
                alert(res.eroare || 'Eroare la crearea contului.');
            }
        }
    } catch (err) {
        if (errorDiv) {
            errorDiv.innerText = "Eroare de conexiune.";
            errorDiv.classList.remove('hidden');
        }
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

async function adaugaTranzactie() {
    const email = document.getElementById('newTxEmail').value;
    const nr_bilete = document.getElementById('newTxCount').value;

    if (!email || !nr_bilete) {
        alert("Introdu email-ul și numărul de bilete!");
        return;
    }

    try {
        const req = await fetch('/api/admin/add-transaction', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, nr_bilete })
        });

        const res = await req.json();

        if (req.ok) {
            alert(`${res.mesaj}\nUUID: ${res.uid_tranzactie}`);
            document.getElementById('newTxEmail').value = '';
            document.getElementById('newTxCount').value = '';
        } else {
            alert(res.eroare || "Eroare la emiterea tranzacției.");
        }
    } catch (err) {
        alert("Eroare de conexiune cu serverul.");
        console.error(err);
    }
}

async function valideazaTranzactie() {
    const uuid = document.getElementById('uuidTx').value;
    const msg = document.getElementById('mesajValidare');
    msg.innerText = "Se validează...";
    msg.style.color = "white";

    try {
        const req = await fetch('/api/admin/validate-transaction', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ uuid })
        });
        const res = await req.json();

        if (req.ok) {
            msg.style.color = "var(--success)";
            msg.innerText = `Tranzacție validă! Acces permis pentru ${res.nr_bilete} persoane.`;
        } else if (res.deja_folosit) {
            msg.style.color = "orange";
            msg.innerText = "ATENȚIE: Această tranzacție a fost deja validată (revendicată)!";
        } else {
            msg.style.color = "var(--danger)";
            msg.innerText = res.eroare || "Tranzacție invalidă sau inexistentă.";
        }
    } catch (err) {
        msg.style.color = "var(--danger)";
        msg.innerText = "Eroare de conexiune cu serverul.";
    }
}

async function faAdmin() {
    const email = document.getElementById('makeAdminEmail').value;

    if (!email) {
        alert("Te rog să introduci un email!");
        return;
    }

    try {
        const req = await fetch('/api/admin/make-user-admin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email })
        });

        const res = await req.json();

        if (req.ok) {
            alert("Utilizatorul a primit rolul de administrator cu succes!");
            document.getElementById('makeAdminEmail').value = '';
        } else {
            alert(res.eroare || "Eroare la modificarea rolului.");
        }
    } catch (err) {
        alert("Eroare de conexiune cu serverul.");
        console.error(err);
    }
}