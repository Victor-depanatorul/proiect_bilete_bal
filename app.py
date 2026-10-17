import os

from flask import Flask, render_template, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import oracledb
import smtplib
from email.mime.text import MIMEText
import secrets
from dotenv import load_dotenv

# INCARCARE CHESTII NECESARE
app = Flask(__name__)
load_dotenv()

# CONFIGURARE BAZĂ DE DATE ORACLE

DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_DSN = os.getenv("DB_DSN")
pool = oracledb.create_pool(user=DB_USER, password=DB_PASS, dsn=DB_DSN, min=2, max=5, increment=1)


# CONFIGURARE EMAIL

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT"))
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

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


# RUTE AFIȘARE PAGINI HTML

@app.route('/')
def home(): return render_template('index.html')


@app.route('/signin')
def signin(): return render_template('signin.html')


@app.route('/signup')
def signup(): return render_template('signup.html')


@app.route('/bilete')
def bilete(): return render_template('bilete.html')


@app.route('/admin')
def admin(): return render_template('admin.html')


# RUTE API

@app.route('/api/register', methods=['POST'])
def api_register():
    date = request.json
    nume = date.get('nume')
    email = date.get('email')
    parola_raw = date.get('parola')

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
    date = request.json
    email = date.get('email')
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
    date = request.json
    email = date.get('email')
    parola_raw = date.get('parola')

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            sql = "SELECT id_utilizator, email, este_admin, parola, cont_verificat FROM utilizator WHERE email = :email"
            cursor.execute(sql, email=email)
            user_row = cursor.fetchone()

            if user_row and check_password_hash(user_row[3], parola_raw):
                user_data = {
                    "id": user_row[0],
                    "email": user_row[1],
                    "este_admin": user_row[2],
                    "cont_verificat": user_row[4]
                }
                return jsonify({"user": user_data}), 200
            else:
                return jsonify({"eroare": "Email sau parolă incorecte"}), 401


@app.route('/api/admin/users', methods=['GET'])
def api_admin_users():
    search_query = request.args.get('q', '').lower()

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            sql = 'SELECT id_utilizator, nume, email, este_admin, cont_verificat FROM utilizator WHERE LOWER(email) LIKE :q OR TO_CHAR(id_utilizator) = :id_exact'
            cursor.execute(sql, q=f"%{search_query}%", id_exact=search_query)

            nume_coloane = [col[0].lower() for col in cursor.description]
            cursor.rowfactory = lambda *args: dict(zip(nume_coloane, args))

            rezultate = cursor.fetchall()
            return jsonify(rezultate), 200


@app.route('/api/admin/transactions', methods=['GET'])
def api_admin_transactions():
    search_query = request.args.get('q', '').lower()

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            sql = '''
                  SELECT t.uuid_tranzactie, t.id_utilizator, u.email, t.nr_bilete, t.revendicat
                  FROM tranzactie t
                           JOIN utilizator u ON t.id_utilizator = u.id_utilizator
                  WHERE LOWER(t.uuid_tranzactie) = :q \
                     OR LOWER(u.email) LIKE :q_like \
                  '''
            cursor.execute(sql, q=search_query, q_like=f"%{search_query}%")

            nume_coloane = [col[0].lower() for col in cursor.description]
            cursor.rowfactory = lambda *args: dict(zip(nume_coloane, args))

            rezultate = cursor.fetchall()
            return jsonify(rezultate), 200


@app.route('/api/admin/add-transaction', methods=['POST'])
def api_add_transaction():
    date = request.json
    email = date.get('email')
    nr_bilete = date.get('nr_bilete')

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
def api_validate_transaction():
    uid_tranzactie = request.json.get('uuid')

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT revendicat, nr_bilete FROM tranzactie WHERE uuid_tranzactie = :uid",
                           uid=uid_tranzactie)
            tx_row = cursor.fetchone()

            if not tx_row:
                return jsonify({"eroare": "Tranzacție inexistentă"}), 404

            revendicat = tx_row[0]
            nr_bilete = tx_row[1]

            if revendicat >= 1:
                return jsonify({"deja_folosit": True}), 400

            cursor.execute("UPDATE tranzactie SET revendicat = 1 WHERE uuid_tranzactie = :uid", uid=uid_tranzactie)
            connection.commit()

            return jsonify({"mesaj": "Tranzacție validată", "nr_bilete": nr_bilete}), 200


@app.route('/api/admin/make-user-admin', methods=['POST'])
def api_make_user_admin():
    email = request.json.get('email')

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
    app.run(host='0.0.0.0', port=5000, debug=True)