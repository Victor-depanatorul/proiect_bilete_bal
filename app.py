from flask import Flask, render_template, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
import oracledb

app = Flask(__name__)

DB_USER = "sgbd_homedb1"
DB_PASS = "oracle"
DB_DSN = "localhost:1521/ORCLPDB"

# Creăm pool-ul de conexiuni la pornirea serverului
pool = oracledb.create_pool(user=DB_USER, password=DB_PASS, dsn=DB_DSN, min=2, max=5, increment=1)

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
    return render_template('bilete.html')


@app.route('/admin')
def admin():
    return render_template('admin.html')


from flask import Flask, render_template, request, jsonify
# Importăm funcțiile de hashing
from werkzeug.security import generate_password_hash, check_password_hash
import oracledb


# ... [Setările pentru app și pool-ul Oracle rămân la fel] ...

@app.route('/api/register', methods=['POST'])
def api_register():
    date = request.json
    nume = date.get('nume')
    email = date.get('email')
    parola_raw = date.get('parola')

    # 1. Hash-uim parola înainte de a interacționa cu baza de date
    parola_hash = generate_password_hash(parola_raw)

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            try:
                # 2. Salvăm hash-ul rezultat, nu parola text
                sql = "INSERT INTO utilizatori (nume, email, parola, este_admin) VALUES (:nume, :email, :parola_hash, 0)"
                cursor.execute(sql, nume=nume, email=email, parola_hash=parola_hash)
                connection.commit()

                return jsonify({"mesaj": "Cont creat cu succes"}), 201
            except oracledb.IntegrityError:
                return jsonify({"eroare": "Acest email este deja folosit"}), 409


@app.route('/api/login', methods=['POST'])
def api_login():
    date = request.json
    email = date.get('email')
    parola_raw = date.get('parola')

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            sql = "SELECT id, email, este_admin, parola FROM utilizatori WHERE email = :email"
            cursor.execute(sql, email=email)
            user_row = cursor.fetchone()

            if user_row and check_password_hash(user_row[3], parola_raw):
                user_data = {
                    "id": user_row[0],
                    "email": user_row[1],
                    "este_admin": user_row[2]
                }
                return jsonify({"user": user_data}), 200
            else:
                return jsonify({"eroare": "Email sau parolă incorecte"}), 401


@app.route('/api/admin/users', methods=['GET'])
def api_admin_users():
    search_query = request.args.get('q', '').lower()

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            sql = "SELECT id, nume, email, este_admin FROM utilizatori WHERE LOWER(email) LIKE :q OR TO_CHAR(id) = :id_exact"
            cursor.execute(sql, q=f"%{search_query}%", id_exact=search_query)

            nume_coloane = [col[0].lower() for col in cursor.description]
            cursor.rowfactory = lambda *args: dict(zip(nume_coloane, args))

            rezultate = cursor.fetchall()
            return jsonify(rezultate), 200


@app.route('/api/admin/validate-ticket', methods=['POST'])
def api_validate_ticket():
    uuid_bilet = request.json.get('uuid')

    with pool.acquire() as connection:
        with connection.cursor() as cursor:
            # Verificăm dacă biletul există și starea lui
            cursor.execute("SELECT validat FROM bilete WHERE uuid = :uuid", uuid=uuid_bilet)
            bilet = cursor.fetchone()

            if not bilet:
                return jsonify({"eroare": "Bilet inexistent"}), 404

            if bilet[0] == 1:
                return jsonify({"deja_folosit": True}), 400

            # Dacă e valid și nefolosit, îl marcăm ca folosit
            cursor.execute("UPDATE bilete SET validat = 1 WHERE uuid = :uuid", uuid=uuid_bilet)
            connection.commit()

            return jsonify({"mesaj": "Bilet validat cu succes"}), 200


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)