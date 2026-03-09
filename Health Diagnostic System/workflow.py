"""
workflow.py — Clinical Workflow DB Layer
Tables: doctor_profiles, lab_profiles, consultations, lab_orders, lab_results
"""
import mysql.connector
from database import get_conn

LAB_TEST_TYPES = [
    "Blood Test", "Urine Test", "X-Ray", "ECG", "MRI / CT Scan", "Ultrasound",
    "Stool Test", "Culture Test", "Liver Function Test", "Kidney Function Test",
    "Thyroid Profile", "Lipid Profile", "HbA1c", "Chest X-Ray",
    "Complete Blood Count (CBC)", "COVID-19 Test", "Dengue Test",
    "Malaria Test", "Typhoid Test", "HIV Test", "Other"
]


def init_workflow_tables():
    conn = get_conn()
    cur  = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS doctor_profiles (
            id             INT          AUTO_INCREMENT PRIMARY KEY,
            user_id        INT          NOT NULL UNIQUE,
            full_name      VARCHAR(128) NOT NULL,
            specialty      VARCHAR(128) NOT NULL,
            qualification  VARCHAR(256),
            experience_yrs INT          DEFAULT 0,
            available      TINYINT(1)   NOT NULL DEFAULT 1,
            created_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lab_profiles (
            id         INT          AUTO_INCREMENT PRIMARY KEY,
            user_id    INT          NOT NULL UNIQUE,
            full_name  VARCHAR(128) NOT NULL,
            lab_name   VARCHAR(128) DEFAULT 'Central Lab',
            created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS consultations (
            id              INT         AUTO_INCREMENT PRIMARY KEY,
            diagnosis_id    INT         NOT NULL,
            patient_user_id INT         NOT NULL,
            doctor_user_id  INT         NOT NULL,
            status          VARCHAR(32) NOT NULL DEFAULT 'pending',
            doctor_notes    TEXT,
            final_diagnosis VARCHAR(256),
            prescription    TEXT,
            follow_up_date  DATE,
            created_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (diagnosis_id)    REFERENCES diagnoses(id),
            FOREIGN KEY (patient_user_id) REFERENCES users(id),
            FOREIGN KEY (doctor_user_id)  REFERENCES users(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lab_orders (
            id              INT         AUTO_INCREMENT PRIMARY KEY,
            consultation_id INT         NOT NULL,
            patient_user_id INT         NOT NULL,
            doctor_user_id  INT         NOT NULL,
            lab_user_id     INT         DEFAULT NULL,
            test_type       VARCHAR(128) NOT NULL,
            test_notes      TEXT,
            priority        VARCHAR(16) NOT NULL DEFAULT 'normal',
            status          VARCHAR(32) NOT NULL DEFAULT 'pending',
            created_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at      DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            FOREIGN KEY (consultation_id)  REFERENCES consultations(id),
            FOREIGN KEY (patient_user_id)  REFERENCES users(id),
            FOREIGN KEY (doctor_user_id)   REFERENCES users(id),
            FOREIGN KEY (lab_user_id)      REFERENCES users(id) ON DELETE SET NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lab_results (
            id           INT  AUTO_INCREMENT PRIMARY KEY,
            order_id     INT  NOT NULL UNIQUE,
            lab_user_id  INT  NOT NULL,
            result_text  TEXT NOT NULL,
            result_value VARCHAR(256),
            unit         VARCHAR(64),
            normal_range VARCHAR(128),
            is_abnormal  TINYINT(1) NOT NULL DEFAULT 0,
            remarks      TEXT,
            created_at   DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_id)    REFERENCES lab_orders(id),
            FOREIGN KEY (lab_user_id) REFERENCES users(id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    conn.commit()

    # Indexes — silently skip if already present
    for idx, tbl, col in [
        ("idx_consult_doctor",   "consultations", "doctor_user_id"),
        ("idx_consult_patient",  "consultations", "patient_user_id"),
        ("idx_consult_status",   "consultations", "status"),
        ("idx_laborder_status",  "lab_orders",    "status"),
        ("idx_laborder_lab",     "lab_orders",    "lab_user_id"),
        ("idx_laborder_consult", "lab_orders",    "consultation_id"),
    ]:
        try:
            cur.execute(f"CREATE INDEX {idx} ON {tbl}({col})")
            conn.commit()
        except Exception:
            conn.rollback()

    cur.close()
    conn.close()
    print("[Workflow] Tables initialised.")


# ── Doctor management ─────────────────────────────────────────────────────────

def create_doctor(username, password, full_name, specialty,
                  qualification="", experience=0):
    from database import register_user
    uid, err = register_user(username, password)
    if err:
        return None, err
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("UPDATE users SET role='doctor' WHERE id=%s", (uid,))
    cur.execute("""
        INSERT INTO doctor_profiles
            (user_id, full_name, specialty, qualification, experience_yrs)
        VALUES (%s,%s,%s,%s,%s)
    """, (uid, full_name, specialty, qualification, experience))
    conn.commit()
    cur.close(); conn.close()
    return uid, None


def create_lab_tech(username, password, full_name, lab_name="Central Lab"):
    from database import register_user
    uid, err = register_user(username, password)
    if err:
        return None, err
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("UPDATE users SET role='lab' WHERE id=%s", (uid,))
    cur.execute(
        "INSERT INTO lab_profiles (user_id, full_name, lab_name) VALUES (%s,%s,%s)",
        (uid, full_name, lab_name)
    )
    conn.commit()
    cur.close(); conn.close()
    return uid, None


def get_all_doctors():
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT dp.*, u.username
        FROM   doctor_profiles dp
        JOIN   users u ON u.id = dp.user_id
        WHERE  dp.available = 1
        ORDER  BY dp.specialty, dp.full_name
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows


def get_all_lab_techs():
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT lp.*, u.username
        FROM   lab_profiles lp
        JOIN   users u ON u.id = lp.user_id
    """)
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows


def get_doctor_profile(user_id):
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM doctor_profiles WHERE user_id=%s", (user_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row


def get_lab_profile(user_id):
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    cur.execute("SELECT * FROM lab_profiles WHERE user_id=%s", (user_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row


# ── Auto-assignment ───────────────────────────────────────────────────────────

def auto_assign_doctor(specialty):
    """
    Return user_id of the available doctor matching the specialty
    with fewest active consultations (load balancing).
    Falls back to any available doctor if none match specialty.
    """
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT dp.user_id, COUNT(c.id) AS active_cases
        FROM   doctor_profiles dp
        LEFT   JOIN consultations c
               ON c.doctor_user_id = dp.user_id
              AND c.status NOT IN ('completed', 'cancelled')
        WHERE  dp.available = 1 AND dp.specialty = %s
        GROUP  BY dp.user_id
        ORDER  BY active_cases ASC
        LIMIT  1
    """, (specialty,))
    row = cur.fetchone()

    if not row:
        # Fallback — any available doctor
        cur.execute("""
            SELECT dp.user_id, COUNT(c.id) AS active_cases
            FROM   doctor_profiles dp
            LEFT   JOIN consultations c
                   ON c.doctor_user_id = dp.user_id
                  AND c.status NOT IN ('completed', 'cancelled')
            WHERE  dp.available = 1
            GROUP  BY dp.user_id
            ORDER  BY active_cases ASC
            LIMIT  1
        """)
        row = cur.fetchone()

    cur.close(); conn.close()
    return row["user_id"] if row else None


# ── Consultations ─────────────────────────────────────────────────────────────

def delete_staff(user_id, role):
    """Delete a doctor or lab tech — cascades all related records. Returns error string or None."""
    conn = get_conn()
    cur  = conn.cursor()
    try:
        if role == "doctor":
            # Get all consultations for this doctor
            cur.execute("SELECT id FROM consultations WHERE doctor_user_id = %s", (user_id,))
            consult_ids = [r[0] for r in cur.fetchall()]
            for cid in consult_ids:
                # Delete lab results for orders in this consultation
                cur.execute("""
                    DELETE lr FROM lab_results lr
                    JOIN lab_orders lo ON lo.id = lr.order_id
                    WHERE lo.consultation_id = %s
                """, (cid,))
                # Delete lab orders
                cur.execute("DELETE FROM lab_orders WHERE consultation_id = %s", (cid,))
            # Delete consultations
            cur.execute("DELETE FROM consultations WHERE doctor_user_id = %s", (user_id,))
            # Delete doctor profile
            cur.execute("DELETE FROM doctor_profiles WHERE user_id = %s", (user_id,))

        else:  # lab
            # Delete lab results submitted by this tech
            cur.execute("DELETE lr FROM lab_results lr WHERE lr.lab_user_id = %s", (user_id,))
            # Unassign their pending orders (set lab_user_id to NULL)
            cur.execute("UPDATE lab_orders SET lab_user_id = NULL WHERE lab_user_id = %s", (user_id,))
            # Delete lab profile
            cur.execute("DELETE FROM lab_profiles WHERE user_id = %s", (user_id,))

        # Finally delete the user account
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
        return None
    except Exception as e:
        conn.rollback()
        return str(e)
    finally:
        cur.close(); conn.close()


def create_consultation(diagnosis_id, patient_user_id, doctor_user_id):
    conn = get_conn()
    cur  = conn.cursor()
    # Prevent duplicates
    cur.execute(
        "SELECT id FROM consultations WHERE diagnosis_id=%s AND patient_user_id=%s",
        (diagnosis_id, patient_user_id)
    )
    existing = cur.fetchone()
    if existing:
        cur.close(); conn.close()
        return existing[0]
    cur.execute("""
        INSERT INTO consultations
            (diagnosis_id, patient_user_id, doctor_user_id, status)
        VALUES (%s,%s,%s,'pending')
    """, (diagnosis_id, patient_user_id, doctor_user_id))
    conn.commit()
    cid = cur.lastrowid
    cur.close(); conn.close()
    return cid


def get_doctor_consultations(doctor_user_id, status=None):
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    base = """
        SELECT c.*,
               p.full_name  AS patient_name, p.age, p.gender, p.city,
               d.top_disease, d.confidence, d.risk_score,
               d.symptoms, d.predictions, d.doctor_type,
               d.created_at AS diagnosis_time
        FROM   consultations c
        JOIN   patients  p ON p.user_id = c.patient_user_id
        JOIN   diagnoses d ON d.id      = c.diagnosis_id
        WHERE  c.doctor_user_id = %s
    """
    if status:
        cur.execute(base + " AND c.status=%s ORDER BY c.created_at DESC",
                    (doctor_user_id, status))
    else:
        cur.execute(base + " ORDER BY c.created_at DESC", (doctor_user_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows


def get_consultation(consultation_id):
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT c.*,
               p.full_name  AS patient_name, p.age, p.gender, p.city,
               d.top_disease, d.confidence, d.risk_score,
               d.symptoms, d.predictions, d.doctor_type,
               d.created_at AS diagnosis_time,
               dp.full_name AS doctor_name, dp.specialty, dp.qualification
        FROM   consultations   c
        JOIN   patients        p  ON p.user_id  = c.patient_user_id
        JOIN   diagnoses       d  ON d.id       = c.diagnosis_id
        JOIN   doctor_profiles dp ON dp.user_id = c.doctor_user_id
        WHERE  c.id = %s
    """, (consultation_id,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row


def update_consultation(consultation_id, doctor_notes, final_diagnosis,
                         prescription, follow_up_date, status):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        UPDATE consultations
        SET doctor_notes=%s, final_diagnosis=%s, prescription=%s,
            follow_up_date=%s, status=%s
        WHERE id=%s
    """, (doctor_notes, final_diagnosis, prescription,
          follow_up_date or None, status, consultation_id))
    conn.commit()
    cur.close(); conn.close()


def get_patient_consultations(patient_user_id):
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT c.*,
               dp.full_name AS doctor_name, dp.specialty,
               d.top_disease, d.confidence, d.risk_score,
               d.created_at AS diagnosis_time,
               COUNT(lo.id)                                        AS total_labs,
               SUM(CASE WHEN lo.status='pending'   THEN 1 ELSE 0 END) AS pending_labs,
               SUM(CASE WHEN lo.status='completed' THEN 1 ELSE 0 END) AS done_labs
        FROM   consultations   c
        JOIN   doctor_profiles dp ON dp.user_id   = c.doctor_user_id
        JOIN   diagnoses       d  ON d.id         = c.diagnosis_id
        LEFT   JOIN lab_orders lo ON lo.consultation_id = c.id
        WHERE  c.patient_user_id = %s
        GROUP  BY c.id, dp.full_name, dp.specialty,
                  d.top_disease, d.confidence, d.risk_score, d.created_at
        ORDER  BY c.created_at DESC
    """, (patient_user_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows


# ── Lab Orders ────────────────────────────────────────────────────────────────

def create_lab_order(consultation_id, patient_user_id, doctor_user_id,
                     test_type, test_notes="", priority="normal"):
    """Auto-assign to lab tech with fewest pending orders."""
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)

    cur.execute("""
        SELECT lp.user_id, COUNT(lo.id) AS pending
        FROM   lab_profiles lp
        LEFT   JOIN lab_orders lo
               ON lo.lab_user_id = lp.user_id AND lo.status = 'pending'
        GROUP  BY lp.user_id
        ORDER  BY pending ASC
        LIMIT  1
    """)
    lab_row     = cur.fetchone()
    lab_user_id = lab_row["user_id"] if lab_row else None

    cur2 = conn.cursor()
    cur2.execute("""
        INSERT INTO lab_orders
            (consultation_id, patient_user_id, doctor_user_id,
             lab_user_id, test_type, test_notes, priority, status)
        VALUES (%s,%s,%s,%s,%s,%s,%s,'pending')
    """, (consultation_id, patient_user_id, doctor_user_id,
          lab_user_id, test_type, test_notes, priority))
    conn.commit()
    oid = cur2.lastrowid
    cur.close(); cur2.close(); conn.close()
    return oid


def get_lab_orders_for_consultation(consultation_id):
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT lo.*,
               lr.result_text, lr.result_value, lr.unit,
               lr.normal_range, lr.is_abnormal, lr.remarks,
               lr.created_at AS result_time,
               lp.full_name  AS lab_tech_name
        FROM   lab_orders lo
        LEFT   JOIN lab_results  lr ON lr.order_id  = lo.id
        LEFT   JOIN lab_profiles lp ON lp.user_id   = lo.lab_user_id
        WHERE  lo.consultation_id = %s
        ORDER  BY lo.created_at DESC
    """, (consultation_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows


def get_lab_tech_orders(lab_user_id, status=None):
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    base = """
        SELECT lo.*,
               p.full_name  AS patient_name, p.age, p.gender,
               dp.full_name AS doctor_name, dp.specialty,
               d.top_disease,
               lr.result_text, lr.is_abnormal
        FROM   lab_orders      lo
        JOIN   patients        p  ON p.user_id  = lo.patient_user_id
        JOIN   doctor_profiles dp ON dp.user_id = lo.doctor_user_id
        JOIN   consultations   c  ON c.id       = lo.consultation_id
        JOIN   diagnoses       d  ON d.id       = c.diagnosis_id
        LEFT   JOIN lab_results lr ON lr.order_id = lo.id
        WHERE  lo.lab_user_id = %s
    """
    if status:
        cur.execute(base + " AND lo.status=%s ORDER BY lo.priority DESC, lo.created_at ASC",
                    (lab_user_id, status))
    else:
        cur.execute(base + " ORDER BY lo.priority DESC, lo.created_at ASC",
                    (lab_user_id,))
    rows = cur.fetchall()
    cur.close(); conn.close()
    return rows


def submit_lab_result(order_id, lab_user_id, result_text, result_value,
                       unit, normal_range, is_abnormal, remarks):
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO lab_results
            (order_id, lab_user_id, result_text, result_value,
             unit, normal_range, is_abnormal, remarks)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            result_text  = VALUES(result_text),
            result_value = VALUES(result_value),
            unit         = VALUES(unit),
            normal_range = VALUES(normal_range),
            is_abnormal  = VALUES(is_abnormal),
            remarks      = VALUES(remarks)
    """, (order_id, lab_user_id, result_text, result_value,
          unit, normal_range, is_abnormal, remarks))
    cur.execute("UPDATE lab_orders SET status='completed' WHERE id=%s", (order_id,))
    conn.commit()
    cur.close(); conn.close()


def get_workflow_stats():
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM consultations WHERE status='pending'")
    pc = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM consultations WHERE status='completed'")
    cc = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM lab_orders WHERE status='pending'")
    pl = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM lab_orders WHERE status='completed'")
    cl = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM doctor_profiles WHERE available=1")
    ad = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM lab_profiles")
    lt = cur.fetchone()[0]
    cur.close(); conn.close()
    return {
        "pending_consults":   pc,
        "completed_consults": cc,
        "pending_labs":       pl,
        "completed_labs":     cl,
        "active_doctors":     ad,
        "lab_techs":          lt,
    }


# Auto-run on import
init_workflow_tables()