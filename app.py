import os
import hashlib
import secrets
import smtplib
from email.mime.text import MIMEText
from functools import wraps

import oracledb
import stripe
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

# INCARCARE CHESTII NECESARE
app = Flask(__name__)
load_dotenv()

# Cheia cu care Flask semnează cookie-ul de sesiune. Pune SECRET_KEY în .env
# (o valoare lungă și aleatoare), nu o lăsa pe cea de dezvoltare.
app.secret_key = os.getenv("SECRET_KEY", "dev-only-schimba-ma")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,   # JavaScript nu poate citi cookie-ul
    SESSION_COOKIE_SAMESITE="Lax",  # protecție de bază împotriva CSRF
)

# CONFIGURARE BAZĂ DE DATE ORACLE

DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_DSN = os.getenv("DB_DSN")
pool = oracledb.create_pool(user=DB_USER, password=DB_PASS, dsn=DB_DSN, min=2, max=5, increment=1)


# CONFIGURARE EMAIL

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")


# CONFIGURARE PLĂȚI (Stripe)

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:5000")

# Prețul se stabilește PE SERVER (din .env sau valoarea de mai jos).
# Browserul trimite doar numărul de bilete, niciodată suma.
PRET_BILET = float(os.getenv("PRET_BILET", "50"))   # RON / bilet
MONEDA = "ron"
MAX_BILETE = 6                                       # maxim bilete / comandă


def trimitere_email_generic(subiect, mesaj, destinatar):
    msg = MIMEText(mesaj)
    msg['Subject'] = subiect
    msg['From'] = f"Balul FMI <{EMAIL_SENDER}>"
    msg['To'] = destinatar

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"Eroare SMTP (Tranzactie): {e}")
        return False


def trimite_email_verificare(destinatar, cod):
    subiect = "Verificare cont - Balul Bobocilor FMI"
    mesaj = f"Salut,\n\nCodul tău de verificare este: {cod}\n\nTe rugăm să introduci acest cod în aplicație pentru a-ți activa contul și a putea cumpăra bilete."

    return trimitere_email_generic(subiect, mesaj, destinatar)


def trimite_email_bilet(destinatar, cod_tranzactie, nr_bilete):
    subiect = "Biletele tale - Balul Bobocilor FMI"
    mesaj = f"Salut,\n\nTranzacția ta a fost înregistrată cu succes!\nAi achiziționat {nr_bilete} bilet(e).\n\nCodul tău de acces (UUID-ul) este:\n{cod_tranzactie}\n\nTe rugăm să prezinți acest cod la intrare (poți să îl salvezi sau să arăți acest email).\n\nDistracție plăcută,\nEchipa Balul FMI"

    return trimitere_email_generic(subiect, mesaj, destinatar)


# DECORATOARE DE ACCES (serverul decide cine are voie, nu browserul)

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"eroare": "Trebuie să fii autentificat"}), 401
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    """Pentru rutele API de admin: 401 dacă nu ești logat, 403 dacă nu ești admin."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"eroare": "Trebuie să fii autentificat"}), 401
        if not session.get("este_admin"):
            return jsonify({"eroare": "Acces interzis"}), 403
        return f(*args, **kwargs)
    return wrapper


def admin_page_required(f):
    """Pentru pagina /admin: redirecționează în loc să dea JSON."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("signin"))
        if not session.get("este_admin"):
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return wrapper


# RUTE AFIȘARE PAGINI HTML

@app.route('/')
def home(): return render_template('index.html')


@app.route('/signin')
def signin(): return render_template('signin.html')


@app.route('/signup')
def signup(): return render_template('signup.html')


@app.route('/bilete')
def bilete():
    return render_template('bilete.html', pret=PRET_BILET, max_bilete=MAX_BILETE)


@app.route('/admin')
@admin_page_required
def admin(): return render_template('admin.html')


# RUTE API: AUTENTIFICARE

@app.route('/api/register', methods=['POST'])
def api_register():
    date = request.get_json(silent=True) or {}
    nume = (date.get('nume') or '').strip()
    email = (date.get('email') or '').strip().lower()
    parola_raw = date.get('parola') or ''

    if not nume or not email or not parola_raw:
        return jsonify({"eroare": "Completează toate câmpurile"}), 400
    if len(parola_raw) < 8:
        return jsonify({"eroare": "Parola trebuie să aibă minim 8 caractere"}), 400

    parola_hash = generate_password_hash(parola_raw)
    cod_generat = str(secrets.randbelow(900000) + 100000)

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id_utilizator FROM utilizator WHERE email = :email", email=email)
            if cursor.fetchone():
                return jsonify({"eroare": "Acest email este deja folosit"}), 409

            try:
                sql = '''INSERT INTO utilizator (nume, email, parola, este_admin, cont_verificat, cod_verificare)
                         VALUES (:nume, :email, :parola_hash, 0, 0, :cod)'''
                cursor.execute(sql, nume=nume, email=email, parola_hash=parola_hash, cod=cod_generat)
                connection.commit()

                succes = trimite_email_verificare(email, cod_generat)
                if not succes:
                    return jsonify({"mesaj": "Cont creat, dar email-ul cu codul nu a putut fi trimis."}), 201

                return jsonify({"mesaj": "Cont creat. Verifică-ți email-ul pentru cod!"}), 201
            except oracledb.IntegrityError:
                return jsonify({"eroare": "Acest email este deja folosit"}), 409


@app.route('/api/verify-email', methods=['POST'])
def api_verify_email():
    date = request.get_json(silent=True) or {}
    email = (date.get('email') or '').strip().lower()
    cod_introdus = date.get('cod')

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            sql = "SELECT id_utilizator FROM utilizator WHERE email = :email AND cod_verificare = :cod"
            cursor.execute(sql, email=email, cod=cod_introdus)
            user_row = cursor.fetchone()

            if user_row:
                id_user = user_row[0]
                cursor.execute(
                    "UPDATE utilizator SET cont_verificat = 1, cod_verificare = NULL WHERE id_utilizator = :id",
                    id=id_user)
                connection.commit()
                return jsonify({"mesaj": "Cont validat cu succes!"}), 200
            else:
                return jsonify({"eroare": "Cod incorect sau cont deja validat!"}), 400


@app.route('/api/login', methods=['POST'])
def api_login():
    date = request.get_json(silent=True) or {}
    email = (date.get('email') or '').strip().lower()
    parola_raw = date.get('parola') or ''

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            sql = "SELECT id_utilizator, email, este_admin, parola, cont_verificat FROM utilizator WHERE email = :email"
            cursor.execute(sql, email=email)
            user_row = cursor.fetchone()

    if user_row and check_password_hash(user_row[3], parola_raw):
        # Sesiunea trăiește pe server (cookie semnat); browserul nu o poate modifica
        session.clear()
        session['user_id'] = user_row[0]
        session['email'] = user_row[1]
        session['este_admin'] = int(user_row[2] or 0)
        session['cont_verificat'] = int(user_row[4] or 0)

        user_data = {
            "id": user_row[0],
            "email": user_row[1],
            "este_admin": session['este_admin'],
            "cont_verificat": session['cont_verificat'],
        }
        return jsonify({"user": user_data}), 200

    return jsonify({"eroare": "Email sau parolă incorecte"}), 401


@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({"mesaj": "Deconectat"}), 200


@app.route('/api/me', methods=['GET'])
def api_me():
    """Spune frontend-ului cine e logat, după sesiunea de pe server."""
    if not session.get("user_id"):
        return jsonify({"user": None}), 200
    return jsonify({"user": {
        "id": session['user_id'],
        "email": session.get('email'),
        "este_admin": session.get('este_admin', 0),
        "cont_verificat": session.get('cont_verificat', 0),
    }}), 200


# RUTE API: PLATĂ CU CARDUL (Stripe)

@app.route('/api/checkout', methods=['POST'])
@login_required
def api_checkout():
    """Creează sesiunea Stripe Checkout. Tranzacția se înregistrează abia după plată (webhook)."""
    if not stripe.api_key:
        return jsonify({"eroare": "Plățile nu sunt configurate pe server"}), 500

    date = request.get_json(silent=True) or {}
    try:
        nr_bilete = int(date.get('nr_bilete'))
    except (TypeError, ValueError):
        return jsonify({"eroare": "Număr de bilete invalid"}), 400

    if nr_bilete < 1 or nr_bilete > MAX_BILETE:
        return jsonify({"eroare": f"Poți cumpăra între 1 și {MAX_BILETE} bilete"}), 400

    try:
        checkout = stripe.checkout.Session.create(
            mode="payment",
            client_reference_id=str(session['user_id']),
            customer_email=session.get('email'),
            metadata={
                "id_utilizator": str(session['user_id']),
                "nr_bilete": str(nr_bilete),
            },
            line_items=[{
                "quantity": nr_bilete,
                "price_data": {
                    "currency": MONEDA,
                    "unit_amount": int(round(PRET_BILET * 100)),  # în subunități (bani)
                    "product_data": {"name": "Bilet - Balul Bobocilor FMI"},
                },
            }],
            success_url=f"{BASE_URL}/bilete?plata=succes",
            cancel_url=f"{BASE_URL}/bilete?plata=anulat",
        )
    except Exception:
        app.logger.exception("Eroare la crearea sesiunii Stripe")
        return jsonify({"eroare": "Nu am putut iniția plata. Încearcă din nou."}), 502

    return jsonify({"url": checkout.url}), 200


def proceseaza_plata_reusita(sesiune):
    """După o plată confirmată: înregistrează tranzacția și trimite UUID-ul pe email."""
    meta = sesiune.get('metadata') or {}
    try:
        id_user = int(meta.get('id_utilizator'))
        nr_bilete = int(meta.get('nr_bilete'))
    except (TypeError, ValueError):
        app.logger.warning("Webhook fără metadata validă")
        return

    # Suma plătită trebuie să fie exact cea așteptată
    if sesiune.get('amount_total') != int(round(PRET_BILET * 100)) * nr_bilete:
        app.logger.error("Sumă neașteptată pentru sesiunea %s", sesiune.get('id'))
        return

    # UUID-ul e derivat din ID-ul sesiunii Stripe: dacă webhook-ul vine de două ori
    # (Stripe retrimite), obținem același UUID și nu emitem tranzacția a doua oară.
    # Astfel nu e nevoie de nicio coloană nouă în baza de date.
    uid_tranzactie = hashlib.sha256(sesiune['id'].encode()).hexdigest()[:32]

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM tranzactie WHERE uuid_tranzactie = :uid", uid=uid_tranzactie)
            if cursor.fetchone():
                return  # deja procesată

            cursor.execute("SELECT email FROM utilizator WHERE id_utilizator = :id", id=id_user)
            user_row = cursor.fetchone()
            if not user_row:
                app.logger.error("Utilizator inexistent pentru plata %s", sesiune.get('id'))
                return
            email = user_row[0]

            try:
                cursor.execute(
                    "INSERT INTO tranzactie (uuid_tranzactie, id_utilizator, nr_bilete, revendicat) "
                    "VALUES (:uid, :id, :nr, 0)",
                    uid=uid_tranzactie, id=id_user, nr=nr_bilete)
                connection.commit()
            except oracledb.IntegrityError:
                return  # două webhook-uri simultane: celălalt a inserat deja

    # Email-ul se trimite după commit; dacă pică, UUID-ul rămâne vizibil pe site
    trimite_email_bilet(email, uid_tranzactie, nr_bilete)


@app.route('/api/stripe/webhook', methods=['POST'])
def stripe_webhook():
    """Apelat de Stripe, server la server. Securitatea vine din semnătură, nu din sesiune."""
    if not STRIPE_WEBHOOK_SECRET:
        return "webhook neconfigurat", 500

    payload = request.get_data()
    semnatura = request.headers.get('Stripe-Signature', '')

    # Fără verificarea semnăturii, oricine ar putea trimite un POST fals și primi bilete
    try:
        event = stripe.Webhook.construct_event(payload, semnatura, STRIPE_WEBHOOK_SECRET)
    except Exception:
        return "semnatura invalida", 400

    if event['type'] in ('checkout.session.completed', 'checkout.session.async_payment_succeeded'):
        obj = event['data']['object']
        if obj.get('payment_status') == 'paid':
            try:
                proceseaza_plata_reusita(obj)
            except Exception:
                app.logger.exception("Eroare la procesarea plății")
                return "eroare interna", 500  # Stripe va retrimite webhook-ul

    return "", 200


@app.route('/api/tranzactiile-mele', methods=['GET'])
@login_required
def api_tranzactiile_mele():
    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT uuid_tranzactie, nr_bilete, revendicat FROM tranzactie "
                "WHERE id_utilizator = :id", id=session['user_id'])
            rezultate = [{"uuid": r[0], "nr_bilete": r[1], "revendicat": int(r[2] or 0)}
                         for r in cursor.fetchall()]
    return jsonify(rezultate), 200


# RUTE API: ADMIN (toate cer sesiune de admin)

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def api_admin_users():
    search_query = request.args.get('q', '').strip().lower()

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            sql = 'SELECT id_utilizator, nume, email, este_admin, cont_verificat FROM utilizator WHERE LOWER(email) LIKE :q OR TO_CHAR(id_utilizator) = :id_exact'
            cursor.execute(sql, q=f"%{search_query}%", id_exact=search_query)

            nume_coloane = [col[0].lower() for col in cursor.description]
            cursor.rowfactory = lambda *args: dict(zip(nume_coloane, args))

            rezultate = cursor.fetchall()
            return jsonify(rezultate), 200


@app.route('/api/admin/transactions', methods=['GET'])
@admin_required
def api_admin_transactions():
    search_query = request.args.get('q', '').strip().lower()

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            sql = '''
                  SELECT t.uuid_tranzactie, t.id_utilizator, u.email, t.nr_bilete, t.revendicat
                  FROM tranzactie t
                           JOIN utilizator u ON t.id_utilizator = u.id_utilizator
                  WHERE LOWER(t.uuid_tranzactie) = :q
                     OR LOWER(u.email) LIKE :q_like
                  '''
            cursor.execute(sql, q=search_query, q_like=f"%{search_query}%")

            nume_coloane = [col[0].lower() for col in cursor.description]
            cursor.rowfactory = lambda *args: dict(zip(nume_coloane, args))

            rezultate = cursor.fetchall()
            return jsonify(rezultate), 200


@app.route('/api/admin/add-transaction', methods=['POST'])
@admin_required
def api_add_transaction():
    date = request.get_json(silent=True) or {}
    email = (date.get('email') or '').strip().lower()
    try:
        nr_bilete = int(date.get('nr_bilete'))
    except (TypeError, ValueError):
        return jsonify({"eroare": "Număr de bilete invalid"}), 400
    if nr_bilete < 1:
        return jsonify({"eroare": "Număr de bilete invalid"}), 400

    uid_tranzactie = secrets.token_hex(16)

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            cursor.execute('SELECT id_utilizator FROM utilizator WHERE email = :email', email=email)
            user_row = cursor.fetchone()

            if not user_row:
                return jsonify({"eroare": "Nu există un cont cu acest email."}), 404

            id_user = user_row[0]

            sql = "INSERT INTO tranzactie (uuid_tranzactie, id_utilizator, nr_bilete, revendicat) VALUES (:uid, :id, :nr, 0)"
            cursor.execute(sql, uid=uid_tranzactie, id=id_user, nr=nr_bilete)
            connection.commit()

            email_trimis = trimite_email_bilet(email, uid_tranzactie, nr_bilete)
            mesaj_succes = "Tranzacție înregistrată. Email-ul a fost trimis cu succes!" if email_trimis else "Tranzacție înregistrată, dar email-ul NU a putut fi trimis."

            return jsonify({
                "mesaj": mesaj_succes,
                "uid_tranzactie": uid_tranzactie
            }), 201


@app.route('/api/admin/validate-transaction', methods=['POST'])
@admin_required
def api_validate_transaction():
    date = request.get_json(silent=True) or {}
    uid_tranzactie = (date.get('uuid') or '').strip()

    if not uid_tranzactie:
        return jsonify({"eroare": "UUID lipsă"}), 400

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            # Un singur UPDATE atomic: două scanări simultane nu pot trece amândouă
            cursor.execute(
                "UPDATE tranzactie SET revendicat = 1 WHERE uuid_tranzactie = :uid AND revendicat = 0",
                uid=uid_tranzactie)

            if cursor.rowcount == 1:
                cursor.execute("SELECT nr_bilete FROM tranzactie WHERE uuid_tranzactie = :uid",
                               uid=uid_tranzactie)
                nr_bilete = cursor.fetchone()[0]
                connection.commit()
                return jsonify({"mesaj": "Tranzacție validată", "nr_bilete": nr_bilete}), 200

            # Nu s-a actualizat nimic: fie nu există, fie era deja revendicată
            cursor.execute("SELECT revendicat FROM tranzactie WHERE uuid_tranzactie = :uid",
                           uid=uid_tranzactie)
            if cursor.fetchone() is None:
                return jsonify({"eroare": "Tranzacție inexistentă"}), 404
            return jsonify({"deja_folosit": True}), 400


@app.route('/api/admin/make-user-admin', methods=['POST'])
@admin_required
def api_make_user_admin():
    date = request.get_json(silent=True) or {}
    email = (date.get('email') or '').strip().lower()

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id_utilizator FROM utilizator WHERE email = :email", email=email)
            utilizator_row = cursor.fetchone()

            if not utilizator_row:
                return jsonify({"eroare": "User inexistent"}), 404

            id_utilizator = utilizator_row[0]

            cursor.execute('''UPDATE utilizator
                              SET este_admin = 1
                              WHERE id_utilizator = :id_utilizator''',
                           id_utilizator=id_utilizator)
            connection.commit()

            return jsonify({"mesaj": "User-ul a fost facut admin"}), 200


if __name__ == '__main__':
    # debug doar la cerere: FLASK_DEBUG=1 în .env sau în terminal când dezvolți
    debug = os.getenv("FLASK_DEBUG") == "1"
    app.run(host='127.0.0.1', port=5000, debug=debug)