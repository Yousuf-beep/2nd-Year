"""
database.py — Full MySQL DBMS layer for MediAI
Auto-migrates existing tables so old installs never break.
"""

import json
import hashlib
import mysql.connector

DB_CONFIG = {
    "host":     "localhost",
    "user":     "root",
    "password": "root123",
    "database": "health_db",
}


def get_conn():
    return mysql.connector.connect(**DB_CONFIG)


def _hash(password):
    return hashlib.sha256(password.encode()).hexdigest()


def init_db():
    # ── Create database if not exists ─────────────────────────────────────────
    bootstrap = mysql.connector.connect(
        host=DB_CONFIG["host"],
        user=DB_CONFIG["user"],
        password=DB_CONFIG["password"],
    )
    cur = bootstrap.cursor()
    cur.execute("CREATE DATABASE IF NOT EXISTS health_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    cur.close()
    bootstrap.close()

    conn = get_conn()
    cur  = conn.cursor()

    # ── CREATE TABLES (skipped safely if they already exist) ──────────────────

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INT          AUTO_INCREMENT PRIMARY KEY,
            username      VARCHAR(64)  UNIQUE NOT NULL,
            password_hash VARCHAR(128) NOT NULL,
            role          VARCHAR(16)  NOT NULL DEFAULT 'patient',
            created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id         INT          AUTO_INCREMENT PRIMARY KEY,
            user_id    INT          NOT NULL UNIQUE,
            full_name  VARCHAR(128) NOT NULL,
            age        INT,
            gender     VARCHAR(16),
            city       VARCHAR(64),
            created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          INT          AUTO_INCREMENT PRIMARY KEY,
            session_key VARCHAR(64)  UNIQUE NOT NULL,
            user_id     INT          DEFAULT NULL,
            mode        VARCHAR(16)  NOT NULL DEFAULT 'form',
            created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS diagnoses (
            id          INT          AUTO_INCREMENT PRIMARY KEY,
            session_id  INT          NOT NULL,
            user_id     INT          DEFAULT NULL,
            symptoms    TEXT         NOT NULL,
            top_disease VARCHAR(128) NOT NULL,
            predictions TEXT         NOT NULL,
            risk_score  INT          NOT NULL DEFAULT 0,
            confidence  FLOAT        NOT NULL DEFAULT 0,
            doctor_type VARCHAR(128),
            created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS adaptive_cases (
            id         INT          AUTO_INCREMENT PRIMARY KEY,
            user_id    INT          DEFAULT NULL,
            symptoms   TEXT         NOT NULL,
            disease    VARCHAR(128) NOT NULL,
            confirmed  TINYINT(1)   NOT NULL DEFAULT 1,
            created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS doctor_map (
            disease    VARCHAR(128) PRIMARY KEY,
            specialty  VARCHAR(128) NOT NULL,
            updated_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS symptom_stats (
            symptom    VARCHAR(128) PRIMARY KEY,
            frequency  INT          NOT NULL DEFAULT 0,
            updated_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS symptom_logs (
            id         INT  AUTO_INCREMENT PRIMARY KEY,
            user_id    INT  NOT NULL,
            log_date   DATE NOT NULL,
            symptoms   TEXT NOT NULL,
            severity   INT  NOT NULL DEFAULT 1,
            notes      TEXT,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE KEY uq_user_date (user_id, log_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()

    # ── MIGRATIONS — add columns that old installs are missing ────────────────
    # Each ALTER is wrapped in try/except — if column already exists MySQL
    # throws error 1060, which we silently skip.
    migrations = [
        "ALTER TABLE sessions  ADD COLUMN user_id    INT           DEFAULT NULL",
        "ALTER TABLE sessions  ADD COLUMN updated_at DATETIME      DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        "ALTER TABLE diagnoses ADD COLUMN user_id    INT           DEFAULT NULL",
        "ALTER TABLE diagnoses ADD COLUMN confidence FLOAT         NOT NULL DEFAULT 0",
        "ALTER TABLE diagnoses ADD COLUMN updated_at DATETIME      DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        "ALTER TABLE adaptive_cases ADD COLUMN user_id INT         DEFAULT NULL",
    ]
    for sql in migrations:
        try:
            cur.execute(sql)
            conn.commit()
        except Exception:
            conn.rollback()   # roll back the failed statement so connection stays usable

    # ── FOREIGN KEYS (add if not present — error 1826 / 1215 if already there) ─
    fk_migrations = [
        "ALTER TABLE sessions      ADD CONSTRAINT fk_sess_user  FOREIGN KEY (user_id)    REFERENCES users(id) ON DELETE SET NULL",
        "ALTER TABLE diagnoses     ADD CONSTRAINT fk_diag_sess  FOREIGN KEY (session_id) REFERENCES sessions(id)",
        "ALTER TABLE diagnoses     ADD CONSTRAINT fk_diag_user  FOREIGN KEY (user_id)    REFERENCES users(id) ON DELETE SET NULL",
        "ALTER TABLE adaptive_cases ADD CONSTRAINT fk_adap_user FOREIGN KEY (user_id)   REFERENCES users(id) ON DELETE SET NULL",
        "ALTER TABLE symptom_logs  ADD CONSTRAINT fk_logs_user  FOREIGN KEY (user_id)    REFERENCES users(id) ON DELETE CASCADE",
    ]
    for sql in fk_migrations:
        try:
            cur.execute(sql)
            conn.commit()
        except Exception:
            conn.rollback()

    # ── INDEXES ───────────────────────────────────────────────────────────────
    indexes = [
        ("idx_diagnoses_top_disease", "diagnoses",      "top_disease"),
        ("idx_diagnoses_created_at",  "diagnoses",      "created_at"),
        ("idx_diagnoses_user_id",     "diagnoses",      "user_id"),
        ("idx_sessions_user_id",      "sessions",       "user_id"),
        ("idx_adaptive_disease",      "adaptive_cases", "disease"),
        ("idx_symptom_stats_freq",    "symptom_stats",  "frequency"),
        ("idx_logs_user_date",        "symptom_logs",   "user_id"),
    ]
    for idx_name, table, col in indexes:
        try:
            cur.execute(f"CREATE INDEX {idx_name} ON {table}({col})")
            conn.commit()
        except Exception:
            conn.rollback()

    # ── STORED PROCEDURES ─────────────────────────────────────────────────────
    try:
        cur.execute("DROP PROCEDURE IF EXISTS get_disease_distribution")
        cur.execute("""
            CREATE PROCEDURE get_disease_distribution(IN lim INT)
            BEGIN
                SELECT top_disease, COUNT(*) AS cnt
                FROM   diagnoses
                GROUP  BY top_disease
                ORDER  BY cnt DESC
                LIMIT  lim;
            END
        """)
        conn.commit()
    except Exception:
        conn.rollback()

    try:
        cur.execute("DROP PROCEDURE IF EXISTS get_patient_history")
        cur.execute("""
            CREATE PROCEDURE get_patient_history(IN uid INT)
            BEGIN
                SELECT d.id, d.top_disease, d.risk_score, d.confidence,
                       d.doctor_type, d.created_at, s.mode
                FROM   diagnoses d
                JOIN   sessions  s ON s.id = d.session_id
                WHERE  d.user_id = uid
                ORDER  BY d.created_at DESC;
            END
        """)
        conn.commit()
    except Exception:
        conn.rollback()

    try:
        cur.execute("DROP PROCEDURE IF EXISTS get_top_symptoms")
        cur.execute("""
            CREATE PROCEDURE get_top_symptoms(IN lim INT)
            BEGIN
                SELECT symptom, frequency
                FROM   symptom_stats
                ORDER  BY frequency DESC
                LIMIT  lim;
            END
        """)
        conn.commit()
    except Exception:
        conn.rollback()

    # ── Seed doctor_map ───────────────────────────────────────────────────────
    try:
        cur.execute("SELECT COUNT(*) FROM doctor_map")
        if cur.fetchone()[0] == 0:
            doctors = [
                ("Malaria","Infectious Disease Specialist"),
                ("Allergy","Allergist"),
                ("Diabetes","Endocrinologist"),
                ("Hypertension","Cardiologist"),
                ("GERD","Gastroenterologist"),
                ("Acne","Dermatologist"),
                ("Psoriasis","Dermatologist"),
                ("Typhoid","General Physician"),
                ("Hepatitis A","Hepatologist"),
                ("Hepatitis B","Hepatologist"),
                ("Hepatitis C","Hepatologist"),
                ("Hepatitis D","Hepatologist"),
                ("Hepatitis E","Hepatologist"),
                ("Urinary tract infection","Urologist"),
                ("Migraine","Neurologist"),
                ("Arthritis","Rheumatologist"),
                ("Dengue","Infectious Disease Specialist"),
                ("Tuberculosis","Pulmonologist"),
                ("Pneumonia","Pulmonologist"),
                ("Bronchial Asthma","Pulmonologist"),
                ("Varicose veins","Vascular Surgeon"),
                ("Hypothyroidism","Endocrinologist"),
                ("Hyperthyroidism","Endocrinologist"),
                ("Hypoglycemia","Endocrinologist"),
                ("Osteoarthristis","Orthopedic Surgeon"),
                ("Paralysis (brain hemorrhage)","Neurologist"),
                ("Jaundice","Gastroenterologist"),
                ("Chicken pox","Dermatologist"),
                ("Dimorphic hemmorhoids(piles)","Gastroenterologist"),
                ("Drug Reaction","Allergist"),
                ("Peptic ulcer diseae","Gastroenterologist"),
                ("Fungal infection","Dermatologist"),
                ("Common Cold","General Physician"),
                ("Cervical spondylosis","Orthopedic Surgeon"),
                ("Heart attack","Cardiologist"),
                ("Gastroenteritis","Gastroenterologist"),
                ("Impetigo","Dermatologist"),
            ]
            cur.executemany(
                "INSERT IGNORE INTO doctor_map (disease, specialty) VALUES (%s,%s)", doctors
            )
            conn.commit()
    except Exception:
        conn.rollback()

    # ── Seed default admin ────────────────────────────────────────────────────
    try:
        cur.execute("SELECT COUNT(*) FROM users WHERE username='admin'")
        if cur.fetchone()[0] == 0:
            cur.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (%s,%s,'admin')",
                ("admin", _hash("admin123"))
            )
            conn.commit()
    except Exception:
        conn.rollback()

    cur.close()
    conn.close()
    print("[DB] MySQL health_db initialised + migrated OK.")


# ── Auth ──────────────────────────────────────────────────────────────────────

def register_user(username, password):
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s,%s)",
            (username, _hash(password))
        )
        uid = cur.lastrowid
        conn.commit()
        cur.close(); conn.close()
        return uid, None
    except mysql.connector.IntegrityError:
        return None, "Username already taken."


def login_user(username, password):
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT id, username, role FROM users WHERE username=%s AND password_hash=%s",
        (username, _hash(password))
    )
    row = cur.fetchone()
    cur.close(); conn.close()
    return row


def save_patient_profile(user_id, full_name, age, gender, city):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO patients (user_id, full_name, age, gender, city)
        VALUES (%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            full_name=VALUES(full_name), age=VALUES(age),
            gender=VALUES(gender), city=VALUES(city)
    """, (user_id, full_name, age, gender, city))
    conn.commit()
    cur.close(); conn.close()


def get_patient_profile(user_id):
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM patients WHERE user_id=%s", (user_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row


# ── Sessions ──────────────────────────────────────────────────────────────────

def create_session(session_key, mode, user_id=None):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        "INSERT INTO sessions (session_key, mode, user_id) VALUES (%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE mode=VALUES(mode), user_id=VALUES(user_id)",
        (session_key, mode, user_id)
    )
    conn.commit()
    sid = cur.lastrowid
    if sid == 0:
        # ON DUPLICATE KEY returns 0 — fetch the real id
        cur.execute("SELECT id FROM sessions WHERE session_key=%s", (session_key,))
        row = cur.fetchone()
        sid = row[0] if row else 0
    cur.close(); conn.close()
    return sid


# ── Diagnoses ─────────────────────────────────────────────────────────────────

def save_diagnosis(session_id, symptoms, predictions, risk_score, doctor_type, user_id=None):
    top_disease = predictions[0][0] if predictions else "Unknown"
    confidence  = round(float(predictions[0][1]) * 100, 1) if predictions else 0
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO diagnoses
            (session_id, user_id, symptoms, top_disease, predictions,
             risk_score, confidence, doctor_type)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (
        session_id, user_id,
        json.dumps(symptoms),
        top_disease,
        json.dumps([(d, round(float(p), 4)) for d, p in predictions]),
        risk_score, confidence, doctor_type
    ))
    diag_id = cur.lastrowid          # ← capture before symptom loop
    for s in symptoms:
        cur.execute("""
            INSERT INTO symptom_stats (symptom, frequency) VALUES (%s, 1)
            ON DUPLICATE KEY UPDATE frequency = frequency + 1
        """, (s,))
    conn.commit()
    cur.close(); conn.close()
    return diag_id                   # ← return directly — no extra query needed


def get_recent_diagnoses(limit=10, days=None):
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    if days:
        cur.execute("""
            SELECT d.*, s.mode FROM diagnoses d
            JOIN sessions s ON s.id = d.session_id
            WHERE d.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            ORDER BY d.created_at DESC LIMIT %s
        """, (days, limit))
    else:
        cur.execute("""
            SELECT d.*, s.mode FROM diagnoses d
            JOIN sessions s ON s.id = d.session_id
            ORDER BY d.created_at DESC LIMIT %s
        """, (limit,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows


def get_patient_history(user_id):
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    cur.callproc("get_patient_history", [user_id])
    rows = []
    for result in cur.stored_results():
        rows = result.fetchall()
    cur.close(); conn.close()
    return rows


def get_top_symptoms(limit=10):
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    cur.callproc("get_top_symptoms", [limit])
    rows = []
    for result in cur.stored_results():
        rows = result.fetchall()
    cur.close(); conn.close()
    return rows


def get_disease_distribution():
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    cur.callproc("get_disease_distribution", [10])
    rows = []
    for result in cur.stored_results():
        rows = result.fetchall()
    cur.close(); conn.close()
    return rows


def get_stats_summary(days=None):
    conn = get_conn()
    cur  = conn.cursor()
    if days:
        cur.execute(
            "SELECT COUNT(*) FROM diagnoses WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)",
            (days,)
        )
    else:
        cur.execute("SELECT COUNT(*) FROM diagnoses")
    total_diagnoses = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM sessions")
    total_sessions  = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE role='patient'")
    total_patients  = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM adaptive_cases")
    total_adaptive  = cur.fetchone()[0]
    cur.close(); conn.close()
    return {
        "total_diagnoses": total_diagnoses,
        "total_sessions":  total_sessions,
        "total_patients":  total_patients,
        "total_adaptive":  total_adaptive,
    }


def get_daily_diagnoses(days=7):
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT DATE(created_at) AS date, COUNT(*) AS cnt
        FROM   diagnoses
        WHERE  created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
        GROUP  BY DATE(created_at)
        ORDER  BY date ASC
    """, (days,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return [{"date": str(r["date"]), "cnt": r["cnt"]} for r in rows]


# ── Adaptive Cases ────────────────────────────────────────────────────────────

def store_case_db(symptoms, disease, user_id=None):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute(
        "INSERT INTO adaptive_cases (symptoms, disease, user_id) VALUES (%s,%s,%s)",
        (",".join(symptoms), disease, user_id)
    )
    conn.commit()
    cur.close(); conn.close()


# ── Doctor Map ────────────────────────────────────────────────────────────────

def get_doctor_db(disease):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("SELECT specialty FROM doctor_map WHERE disease=%s", (disease,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row[0] if row else "General Physician"


# ── Auto-run on import ────────────────────────────────────────────────────────
init_db()