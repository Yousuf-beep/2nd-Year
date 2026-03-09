"""
symptom_diary.py — Symptom Diary / Timeline feature
Logs daily symptoms per user so trends can be visualized over time.
"""

import json
import mysql.connector
from database import get_conn


def init_diary_table():
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS symptom_logs (
            id          INT          AUTO_INCREMENT PRIMARY KEY,
            user_id     INT          NOT NULL,
            log_date    DATE         NOT NULL,
            symptoms    TEXT         NOT NULL,
            severity    INT          NOT NULL DEFAULT 1,
            notes       TEXT,
            created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
            UNIQUE KEY uq_user_date (user_id, log_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    # Index for fast date-range queries
    try:
        cur.execute("CREATE INDEX idx_logs_user_date ON symptom_logs(user_id, log_date)")
    except Exception:
        pass
    conn.commit()
    cur.close()
    conn.close()


def log_symptoms(user_id: int, log_date: str, symptoms: list,
                 severity: int = 1, notes: str = ""):
    """Insert or update a symptom log for a given date."""
    conn = get_conn()
    cur  = conn.cursor()
    cur.execute("""
        INSERT INTO symptom_logs (user_id, log_date, symptoms, severity, notes)
        VALUES (%s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            symptoms = VALUES(symptoms),
            severity = VALUES(severity),
            notes    = VALUES(notes)
    """, (user_id, log_date, json.dumps(symptoms), severity, notes))
    conn.commit()
    cur.close()
    conn.close()


def get_diary(user_id: int, days: int = 14) -> list:
    """Return symptom logs for the last N days."""
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT log_date, symptoms, severity, notes
        FROM   symptom_logs
        WHERE  user_id  = %s
          AND  log_date >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
        ORDER  BY log_date ASC
    """, (user_id, days))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = []
    for r in rows:
        result.append({
            "date":     str(r["log_date"]),
            "symptoms": json.loads(r["symptoms"]),
            "severity": r["severity"],
            "notes":    r["notes"] or "",
        })
    return result


def get_trend_data(user_id: int, days: int = 14) -> dict:
    """
    Returns chart-ready data:
    - dates list
    - severity list
    - symptom_counts list
    - most_common symptoms
    """
    diary = get_diary(user_id, days)
    if not diary:
        return {"dates": [], "severity": [], "counts": [], "common": []}

    dates     = [d["date"] for d in diary]
    severity  = [d["severity"] for d in diary]
    counts    = [len(d["symptoms"]) for d in diary]

    # Most common symptoms over the period
    freq = {}
    for d in diary:
        for s in d["symptoms"]:
            freq[s] = freq.get(s, 0) + 1
    common = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "dates":    dates,
        "severity": severity,
        "counts":   counts,
        "common":   [{"symptom": s, "count": c} for s, c in common],
    }


# Auto-init when imported
init_diary_table()