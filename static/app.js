// ==========================================
// GESTIUNE SESIUNE ȘI NAVIGAȚIE
// ==========================================

function updateNav() {
    // Preluăm datele utilizatorului din localStorage
    const user = JSON.parse(localStorage.getItem('user'));

    // Selectăm butoanele din navbar
    const btnLogin = document.getElementById('btn-login');
    const btnRegister = document.getElementById('btn-register');
    const btnLogout = document.getElementById('btn-logout');
    const btnAdmin = document.getElementById('btn-admin');

    if (user) {
        // Dacă utilizatorul este logat, ascundem Sign In / Sign Up
        if(btnLogin) btnLogin.classList.add('hidden');
        if(btnRegister) btnRegister.classList.add('hidden');

        // Afișăm butonul de Logout
        if(btnLogout) btnLogout.classList.remove('hidden');

        // Dacă utilizatorul este admin (1 sau true în baza de date), afișăm butonul de Panou Admin
        if (btnAdmin && (user.este_admin === 1 || user.este_admin === true)) {
            btnAdmin.classList.remove('hidden');
        }
    } else {
        // Dacă nu este logat, afișăm Sign In / Sign Up
        if(btnLogin) btnLogin.classList.remove('hidden');
        if(btnRegister) btnRegister.classList.remove('hidden');

        // Ascundem Logout și Panou Admin
        if(btnLogout) btnLogout.classList.add('hidden');
        if(btnAdmin) btnAdmin.classList.add('hidden');
    }
}

function logout() {
    // Ștergem sesiunea și redirecționăm către acasă
    localStorage.removeItem('user');
    window.location.href = '/';
}

// Rulăm verificarea la fiecare încărcare a oricărei pagini
document.addEventListener('DOMContentLoaded', updateNav);


// ==========================================
// AUTENTIFICARE (SIGN IN / SIGN UP)
// ==========================================

async function handleLogin(e) {
    e.preventDefault(); // Oprim reîncărcarea paginii generată de <form>

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
            // Salvăm datele returnate de server (id, email, este_admin etc.) în browser
            localStorage.setItem('user', JSON.stringify(res.user));
            alert('Te-ai autentificat cu succes!');
            window.location.href = '/'; // Redirecționare către pagina principală
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
            window.location.href = '/signin'; // Redirecționare către pagina de logare
        } else {
            alert(res.eroare || 'Eroare la crearea contului.');
        }
    } catch (err) {
        console.error("Eroare la request-ul de inregistrare:", err);
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

        // Afișăm rezultatul JSON formatat frumos pe ecran
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
            document.getElementById('newTicketEmail').value = ''; // Golim câmpul
        } else {
            const res = await req.json();
            alert(res.eroare || "Eroare la emiterea biletului.");
        }
    } catch (err) {
        console.error(err);
        alert("Eroare de conexiune.");
    }
}