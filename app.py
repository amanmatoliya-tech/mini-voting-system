from flask import Flask, render_template, request, redirect, url_for, session, flash
from utils.db import get_conn
from utils.security import hash_password, verify_password
import os

app = Flask(__name__)
app.secret_key = os.urandom(24)

# Disable Browser Back Button Cache
@app.after_request
def after_request(response):
    response.headers["Cache-Control"] = "no-store"
    return response
 
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# Initialize database
def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # Create tables
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY,
        college_id TEXT UNIQUE,
        password_hash TEXT,
        has_voted INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS elections (
        id INTEGER PRIMARY KEY,
        name TEXT,
        is_active INTEGER DEFAULT 1
    );

    CREATE TABLE IF NOT EXISTS candidates (
        id INTEGER PRIMARY KEY,
        election_id INTEGER,
        name TEXT,
        photo TEXT,
        FOREIGN KEY (election_id) REFERENCES elections(id)
    );

    CREATE TABLE IF NOT EXISTS votes (
        id INTEGER PRIMARY KEY,
        election_id INTEGER,
        candidate_id INTEGER,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (election_id) REFERENCES elections(id),
        FOREIGN KEY (candidate_id) REFERENCES candidates(id)
    );
    """)

    # Insert default data only if no election exists
    cur.execute("SELECT COUNT(*) FROM elections")
    if cur.fetchone()[0] == 0:

        # Create election
        cur.execute("INSERT INTO elections (name, is_active) VALUES (?, ?)", ("  Council of CR  2025", 1))
        election_id = cur.lastrowid

        # Add default candidates WITH PHOTOS
        cur.executemany(
            "INSERT INTO candidates (election_id, name, photo) VALUES (?, ?, ?)",
            [
                (election_id, "Aman", "aman.jpg"),
                (election_id, "Ankit", "ankit.jpg"),
                (election_id, "Aayush", "aayush.jpg")
            ]
        )

        # Add 64 auto-generated students
        students = []
        for i in range(1, 65):
            roll = f"0905CS241{str(i).zfill(3)}"
            password = f"{roll}#"
            students.append((roll, hash_password(password)))

        cur.executemany(
            "INSERT INTO students (college_id, password_hash) VALUES (?, ?)",
            students
        )

        # commit initial inserts
        conn.commit()

    conn.close()

# Home
@app.route('/')
def home():
    if 'student' in session:
        return redirect(url_for('vote'))
    return redirect(url_for('login'))

# Register
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        college_id = request.form['college_id'].strip()
        password = request.form['password']
        confirm = request.form['confirm']

        if password != confirm:
            flash("Passwords do not match!", "danger")
            return redirect(url_for('register'))

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT * FROM students WHERE college_id=?", (college_id,))
        if cur.fetchone():
            flash("College ID already registered!", "danger")
            conn.close()
            return redirect(url_for('register'))

        cur.execute("INSERT INTO students (college_id, password_hash) VALUES (?, ?)",
                    (college_id, hash_password(password)))

        conn.commit()
        conn.close()

        flash("Registration successful!", "success")
        return redirect(url_for('login'))

    return render_template('register.html')

# Login
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        cid = request.form['college_id'].strip()
        password = request.form['password']

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT * FROM students WHERE college_id=?", (cid,))
        user = cur.fetchone()
        conn.close()

        if user and verify_password(user['password_hash'], password):
            session['student'] = {'id': user['id'], 'college_id': cid}
            return redirect(url_for('vote'))

        flash("Invalid credentials!", "danger")
        return redirect(url_for('login'))

    return render_template('login.html')

# Vote
@app.route('/vote', methods=['GET', 'POST'])
def vote():
    if 'student' not in session:
        return redirect(url_for('login'))

    sid = session['student']['id']

    conn = get_conn()
    cur = conn.cursor()

    # Get active election
    cur.execute("SELECT * FROM elections WHERE is_active=1")
    election = cur.fetchone()

    if not election:
        conn.close()
        return "No active election", 404

    # Check if student has already voted
    cur.execute("SELECT has_voted FROM students WHERE id=?", (sid,))
    row = cur.fetchone()
    has_voted = bool(row['has_voted']) if row else False

    # Handle vote submit
    if request.method == 'POST':
        if has_voted:
            conn.close()
            return redirect(url_for('thanks'))

        candidate_id_raw = request.form.get('candidate')
        if not candidate_id_raw:
            flash("Please select a candidate.", "danger")
            conn.close()
            return redirect(url_for('vote'))

        try:
            candidate_id = int(candidate_id_raw)
        except ValueError:
            flash("Invalid candidate selection.", "danger")
            conn.close()
            return redirect(url_for('vote'))

        # Validate candidate belongs to active election
        cur.execute(
            "SELECT id FROM candidates WHERE id=? AND election_id=?",
            (candidate_id, election['id'])
        )
        candidate_ok = cur.fetchone()
        if not candidate_ok:
            flash("Invalid candidate!", "danger")
            conn.close()
            return redirect(url_for('vote'))

        try:
            # Save vote
            cur.execute(
                "INSERT INTO votes (election_id, candidate_id) VALUES (?, ?)",
                (election['id'], candidate_id)
            )
            cur.execute("UPDATE students SET has_voted=1 WHERE id=?", (sid,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            flash("Error saving vote. Try again.", "danger")
            conn.close()
            return redirect(url_for('vote'))

        conn.close()
        return redirect(url_for('thanks'))

    # Load all candidates (photo included)
    cur.execute(
        "SELECT id, name, photo FROM candidates WHERE election_id=?",
        (election['id'],)
    )
    candidates = cur.fetchall()

    conn.close()
    return render_template('vote.html', election=election, candidates=candidates, has_voted=has_voted)


@app.route('/fixphotos')
def fixphotos():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("UPDATE candidates SET photo='aman.jpg' WHERE name='Aman'")
    cur.execute("UPDATE candidates SET photo='ankit.jpg' WHERE name='Ankit'")
    cur.execute("UPDATE candidates SET photo='aayush.jpg' WHERE name='Aayush'")

    conn.commit()
    conn.close()
    return "Photos updated!"


@app.route('/thanks')
def thanks():
    return render_template('thanks.html')


# Admin route 
ADMIN_PASS = "admin123"

@app.route('/admin', methods=['GET', 'POST'])
def admin():

    # ---------- ADMIN LOGIN ----------
    if request.method == 'POST' and 'admin_login' in request.form:
        if request.form['password'] == ADMIN_PASS:
            session['admin'] = True
            return redirect(url_for('admin'))
        flash("Wrong admin password", "danger")
        return redirect(url_for('admin'))

    # If admin not logged in → show login
    if 'admin' not in session:
        return render_template('admin.html', logged_in=False)

    # ---------- ADMIN LOGGED IN ----------
    conn = get_conn()
    cur = conn.cursor()

    # ---------- CREATE ELECTION ----------
    if request.method == 'POST' and 'create_election' in request.form:
        name = request.form.get('election_name', '').strip()

        if name == "":
            flash("Election name cannot be empty!", "danger")
        else:
            try:
                cur.execute(
                    "INSERT INTO elections (name, is_active) VALUES (?, 1)",
                    (name,)
                )
                conn.commit()
                flash("Election created successfully!", "success")
            except:
                conn.rollback()
                flash("Error creating election!", "danger")

    # ---------- ADD CANDIDATE ----------
    if request.method == 'POST' and 'add_candidate' in request.form:
        eid = request.form.get('election_id')
        cname = request.form.get('candidate_name', '').strip()

        if not eid:
            flash("Select an election!", "danger")
        else:
            try:
                eid_int = int(eid)
            except:
                flash("Invalid election!", "danger")
                eid_int = None

            if eid_int and cname != "":
                # check duplicate
                cur.execute(
                    "SELECT id FROM candidates WHERE election_id=? AND name=?",
                    (eid_int, cname)
                )
                if cur.fetchone():
                    flash("Candidate already exists!", "danger")
                else:
                    cur.execute(
                        "INSERT INTO candidates (election_id, name, photo) VALUES (?, ?, ?)",
                        (eid_int, cname, "default.png")
                    )
                    conn.commit()
                    flash("Candidate added!", "success")

    # ---------- LOAD ELECTIONS ----------
    cur.execute("SELECT * FROM elections ORDER BY id DESC")
    elections = cur.fetchall()

    # ---------- LOAD RESULTS ----------
    results = {}
    for e in elections:
        cur.execute("""
            SELECT c.id, c.name, c.photo, COUNT(v.id) AS votes
            FROM candidates c
            LEFT JOIN votes v ON c.id = v.candidate_id
            WHERE c.election_id=?
            GROUP BY c.id
            ORDER BY votes DESC
        """, (e['id'],))
        results[e['name']] = cur.fetchall()

    # ---------- STUDENTS ----------
    cur.execute("SELECT college_id, has_voted FROM students")
    students = cur.fetchall()

    conn.close()

    return render_template(
        'admin.html',
        logged_in=True,
        elections=elections,
        results=results,
        students=students
    )


# ---------------- DELETE CANDIDATE ROUTE ----------------
@app.route('/delete_candidate/<int:cid>', methods=['POST'])
def delete_candidate(cid):
    if 'admin' not in session:
        return redirect(url_for('admin'))

    conn = get_conn()
    cur = conn.cursor()

    # delete votes first
    cur.execute("DELETE FROM votes WHERE candidate_id=?", (cid,))

    # delete candidate
    cur.execute("DELETE FROM candidates WHERE id=?", (cid,))

    conn.commit()
    conn.close()

    flash("Candidate deleted successfully!", "success")
    return redirect(url_for('admin'))
# Run app

if __name__ == '__main__':
    # ensure DB exists
    init_db()
    app.run(debug=True)







