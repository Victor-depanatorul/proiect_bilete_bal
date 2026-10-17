import os
import uuid
from functools import wraps

import oracledb
import stripe
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# Cheia cu care Flask semnează cookie-ul de sesiune (în producție: variabilă de mediu)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-schimba-ma")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

DB_USER = os.environ.get("DB_USER", "sgbd_homedb1")
DB_PASS = os.environ.get("DB_PASS", "oracle")
DB_DSN = os.environ.get("DB_DSN", "localhost:1521/ORCLPDB")

pool = oracledb.create_pool(user=DB_USER, password=DB_PASS, dsn=DB_DSN,
                            min=2, max=5, increment=1)

# ==========================================
# CONFIGURARE PLĂȚI (Stripe)
# ==========================================
stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:5000")

# Prețurile sunt stabilite AICI, pe server. Browserul trimite doar tipul biletului,
# niciodată suma (altfel oricine și-ar putea cumpăra bilete cu 1 leu).
PRETURI = {
    "standard": {"nume": "Bilet Standard - Balul Bobocilor FMI", "suma": 50.00},
    "vip":      {"nume": "Bilet VIP - Balul Bobocilor FMI",      "suma": 100.00},
}
MONEDA = "ron"


# ==========================================
# DECORATOARE DE ACCES
# ==========================================

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"eroare": "Trebuie să fii autentificat"}), 401
        return f(*args, **kwargs)
    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"eroare": "Trebuie să fii autentificat"}), 401
        if not session.get("este_admin"):
            return jsonify({"eroare": "Acces interzis"}), 403
        return f(*args, **kwargs)
    return wrapper


def admin_page_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("signin"))
        if not session.get("este_admin"):
            return redirect(url_for("home"))
        return f(*args, **kwargs)
    return wrapper


# ==========================================
# PAGINI
# ==========================================

@app.route('/')
def home():
    return render_template('index.html')


@app.route('/signin')
def signin():
    return render_template('signin.html')


@app.route('/signup')
def signup():
    return render_template('signup.html')


@app.route('/bilete')
def bilete():
    return render_template('bilete.html', preturi=PRETURI)


@app.route('/admin')
@admin_page_required
def admin():
    return render_template('admin.html')


# ==========================================
# AUTENTIFICARE
# ==========================================

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

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            try:
                sql = ("INSERT INTO utilizatori (nume, email, parola, este_admin) "
                       "VALUES (:nume, :email, :parola_hash, 0)")
                cursor.execute(sql, nume=nume, email=email, parola_hash=parola_hash)
                connection.commit()
                return jsonify({"mesaj": "Cont creat cu succes"}), 201
            except oracledb.IntegrityError:
                return jsonify({"eroare": "Acest email este deja folosit"}), 409


@app.route('/api/login', methods=['POST'])
def api_login():
    date = request.get_json(silent=True) or {}
    email = (date.get('email') or '').strip().lower()
    parola_raw = date.get('parola') or ''

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            sql = "SELECT id, email, este_admin, parola FROM utilizatori WHERE email = :email"
            cursor.execute(sql, email=email)
            user_row = cursor.fetchone()

    if user_row and check_password_hash(user_row[3], parola_raw):
        session.clear()
        session['user_id'] = user_row[0]
        session['email'] = user_row[1]
        session['este_admin'] = int(user_row[2] or 0)

        return jsonify({"user": {
            "id": user_row[0],
            "email": user_row[1],
            "este_admin": session['este_admin'],
        }}), 200

    return jsonify({"eroare": "Email sau parolă incorecte"}), 401


@app.route('/api/logout', methods=['POST'])
def api_logout():
    session.clear()
    return jsonify({"mesaj": "Deconectat"}), 200


@app.route('/api/me', methods=['GET'])
def api_me():
    if not session.get("user_id"):
        return jsonify({"user": None}), 200
    return jsonify({"user": {
        "id": session['user_id'],
        "email": session.get('email'),
        "este_admin": session.get('este_admin', 0),
    }}), 200


# ==========================================
# PLĂȚI: CHECKOUT
# ==========================================

@app.route('/api/checkout', methods=['POST'])
@login_required
def api_checkout():
    """Creează tranzacția PENDING și trimite userul la pagina de plată Stripe."""
    if not stripe.api_key:
        return jsonify({"eroare": "Plățile nu sunt configurate pe server"}), 500

    date = request.get_json(silent=True) or {}
    tip = date.get('tip')
    if tip not in PRETURI:
        return jsonify({"eroare": "Tip de bilet invalid"}), 400

    info = PRETURI[tip]
    suma = info["suma"]

    # 1. Rând PENDING în baza noastră; ID-ul lui e legătura cu plata de la Stripe
    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            out_id = cursor.var(int)
            cursor.execute(
                "INSERT INTO tranzactii (utilizator_id, tip, suma, status) "
                "VALUES (:uid, :tip, :suma, 'PENDING') RETURNING id INTO :out_id",
                uid=session['user_id'], tip=tip, suma=suma, out_id=out_id)
            tranzactie_id = int(out_id.getvalue()[0])
            connection.commit()

    # 2. Sesiune Stripe Checkout
    try:
        checkout = stripe.checkout.Session.create(
            mode="payment",
            client_reference_id=str(tranzactie_id),
            customer_email=session.get('email'),
            line_items=[{
                "quantity": 1,
                "price_data": {
                    "currency": MONEDA,
                    "unit_amount": int(round(suma * 100)),  # în subunități (bani)
                    "product_data": {"name": info["nume"]},
                },
            }],
            success_url=f"{BASE_URL}/bilete?plata=succes",
            cancel_url=f"{BASE_URL}/bilete?plata=anulat",
        )
    except Exception:
        app.logger.exception("Eroare la crearea sesiunii Stripe")
        with pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute("UPDATE tranzactii SET status = 'FAILED' WHERE id = :id",
                               id=tranzactie_id)
                connection.commit()
        return jsonify({"eroare": "Nu am putut iniția plata. Încearcă din nou."}), 502

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            cursor.execute("UPDATE tranzactii SET id_sesiune = :sid WHERE id = :id",
                           sid=checkout.id, id=tranzactie_id)
            connection.commit()

    return jsonify({"url": checkout.url}), 200


# ==========================================
# PLĂȚI: WEBHOOK (apelat de Stripe, server la server)
# ==========================================

def proceseaza_plata_reusita(sesiune):
    """Marchează tranzacția PAID și emite biletul, totul într-o singură tranzacție DB."""
    try:
        tranzactie_id = int(sesiune.get('client_reference_id'))
    except (TypeError, ValueError):
        app.logger.warning("Webhook fără client_reference_id valid")
        return

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT utilizator_id, tip, suma FROM tranzactii "
                "WHERE id = :id AND status = 'PENDING'", id=tranzactie_id)
            rand = cursor.fetchone()
            if rand is None:
                return  # necunoscută sau deja procesată (webhook retrimis)

            utilizator_id, tip, suma = rand

            # Suma plătită trebuie să fie exact cea din baza noastră
            if sesiune.get('amount_total') != int(round(float(suma) * 100)):
                app.logger.error("Sumă diferită pentru tranzacția %s", tranzactie_id)
                return

            # UPDATE atomic: dacă webhook-ul vine de două ori, a doua oară rowcount = 0
            cursor.execute(
                "UPDATE tranzactii SET status = 'PAID', id_procesator = :pid "
                "WHERE id = :id AND status = 'PENDING'",
                pid=sesiune.get('payment_intent'), id=tranzactie_id)

            if cursor.rowcount == 1:
                cursor.execute(
                    "INSERT INTO bilete (uuid, utilizator_id, tranzactie_id, tip, validat) "
                    "VALUES (:u, :uid, :tid, :tip, 0)",
                    u=str(uuid.uuid4()), uid=utilizator_id, tid=tranzactie_id, tip=tip)

            connection.commit()


@app.route('/api/stripe/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.get_data()
    semnatura = request.headers.get('Stripe-Signature', '')

    if not STRIPE_WEBHOOK_SECRET:
        return "webhook neconfigurat", 500

    # Fără verificarea semnăturii, oricine ar putea trimite un POST fals și primi bilete
    try:
        event = stripe.Webhook.construct_event(payload, semnatura, STRIPE_WEBHOOK_SECRET)
    except Exception:
        return "semnatura invalida", 400

    obj = event['data']['object']

    if event['type'] in ('checkout.session.completed',
                         'checkout.session.async_payment_succeeded'):
        if obj.get('payment_status') == 'paid':
            proceseaza_plata_reusita(obj)

    elif event['type'] == 'checkout.session.expired':
        with pool.acquire() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE tranzactii SET status = 'FAILED' "
                    "WHERE id_sesiune = :sid AND status = 'PENDING'", sid=obj.get('id'))
                connection.commit()

    return "", 200


# ==========================================
# BILETELE UTILIZATORULUI
# ==========================================

@app.route('/api/bilete-mele', methods=['GET'])
@login_required
def api_bilete_mele():
    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT uuid, tip, validat FROM bilete "
                "WHERE utilizator_id = :uid ORDER BY tranzactie_id DESC NULLS LAST",
                uid=session['user_id'])
            rezultate = [{"uuid": r[0], "tip": r[1], "validat": int(r[2] or 0)}
                         for r in cursor.fetchall()]
    return jsonify(rezultate), 200


# ==========================================
# API ADMIN
# ==========================================

@app.route('/api/admin/users', methods=['GET'])
@admin_required
def api_admin_users():
    search_query = request.args.get('q', '').strip().lower()

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            sql = ("SELECT id, nume, email, este_admin FROM utilizatori "
                   "WHERE LOWER(email) LIKE :q OR TO_CHAR(id) = :id_exact")
            cursor.execute(sql, q=f"%{search_query}%", id_exact=search_query)

            nume_coloane = [col[0].lower() for col in cursor.description]
            cursor.rowfactory = lambda *args: dict(zip(nume_coloane, args))

            return jsonify(cursor.fetchall()), 200


@app.route('/api/admin/transactions', methods=['GET'])
@admin_required
def api_admin_transactions():
    search_query = request.args.get('q', '').strip().lower()

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            sql = ("SELECT t.id, u.email, t.tip, t.suma, t.status, t.id_procesator, "
                   "TO_CHAR(t.creat_la, 'YYYY-MM-DD HH24:MI') AS creat_la "
                   "FROM tranzactii t JOIN utilizatori u ON u.id = t.utilizator_id "
                   "WHERE LOWER(u.email) LIKE :q OR TO_CHAR(t.id) = :id_exact "
                   "ORDER BY t.id DESC")
            cursor.execute(sql, q=f"%{search_query}%", id_exact=search_query)

            nume_coloane = [col[0].lower() for col in cursor.description]
            cursor.rowfactory = lambda *args: dict(zip(nume_coloane, args))

            return jsonify(cursor.fetchall()), 200


@app.route('/api/admin/add-ticket', methods=['POST'])
@admin_required
def api_admin_add_ticket():
    """Emitere manuală (ex: invitați). tranzactie_id rămâne NULL."""
    date = request.get_json(silent=True) or {}
    email = (date.get('email') or '').strip().lower()
    tip = date.get('tip')

    if not email or tip not in PRETURI:
        return jsonify({"eroare": "Email sau tip invalid"}), 400

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM utilizatori WHERE email = :email", email=email)
            user = cursor.fetchone()
            if user is None:
                return jsonify({"eroare": "Nu există utilizator cu acest email"}), 404

            cursor.execute(
                "INSERT INTO bilete (uuid, utilizator_id, tip, validat) "
                "VALUES (:u, :uid, :tip, 0)",
                u=str(uuid.uuid4()), uid=user[0], tip=tip)
            connection.commit()

    return jsonify({"mesaj": "Bilet emis"}), 201


@app.route('/api/admin/validate-ticket', methods=['POST'])
@admin_required
def api_validate_ticket():
    date = request.get_json(silent=True) or {}
    uuid_bilet = (date.get('uuid') or '').strip()

    if not uuid_bilet:
        return jsonify({"eroare": "UUID lipsă"}), 400

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE bilete SET validat = 1 WHERE uuid = :uuid AND validat = 0",
                uuid=uuid_bilet)

            if cursor.rowcount == 1:
                connection.commit()
                return jsonify({"mesaj": "Bilet validat cu succes"}), 200

            cursor.execute("SELECT validat FROM bilete WHERE uuid = :uuid", uuid=uuid_bilet)
            if cursor.fetchone() is None:
                return jsonify({"eroare": "Bilet inexistent"}), 404
            return jsonify({"deja_folosit": True}), 400


if __name__ == '__main__':
    debug = os.environ.get("FLASK_DEBUG") == "1"
    app.run(host='127.0.0.1', port=5000, debug=debug)