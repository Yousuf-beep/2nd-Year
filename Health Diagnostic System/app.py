"""
app.py — MediAI Complete Flask Application
"""

import uuid, json
from functools import wraps
from flask import (Flask, render_template, request, session,
                   jsonify, redirect, url_for, flash, Response)
import pandas as pd

from ml_model import predict_disease, symptom_columns, get_confidence
from chatbot_engine import (next_question, parse_free_text,
                             get_severity_question, get_severity_options,
                             get_possible_count)
from database import (
    create_session, save_diagnosis, store_case_db, get_doctor_db,
    get_recent_diagnoses, get_top_symptoms, get_disease_distribution,
    get_stats_summary, get_daily_diagnoses, get_patient_history,
    register_user, login_user, save_patient_profile, get_patient_profile,
    get_conn
)
from mail import configure_mail, send_diagnosis_email
from regional_intelligence import get_regional_alerts, check_emergency
from symptom_diary import log_symptoms, get_diary, get_trend_data
from pdf_report import generate_report
from workflow import (
    create_doctor, create_lab_tech, get_all_doctors, get_all_lab_techs,
    get_doctor_profile, get_lab_profile, auto_assign_doctor,
    create_consultation, get_doctor_consultations, get_consultation,
    update_consultation, get_patient_consultations,
    create_lab_order, get_lab_orders_for_consultation,
    get_lab_tech_orders, submit_lab_result,
    get_workflow_stats, LAB_TEST_TYPES
)

app = Flask(__name__)
app.secret_key = "mediAI_secret_2024_xyz"
DAILY_API_KEY = "YOUR_DAILY_API_KEY"   # replace with your key from daily.co
app.jinja_env.filters["from_json"] = json.loads
configure_mail(app)

description_df = pd.read_csv("dataset/symptom_Description.csv")
precaution_df  = pd.read_csv("dataset/symptom_precaution.csv")
severity_df    = pd.read_csv("dataset/Symptom-severity.csv")
chatbot_states = {}


# ── Decorators ────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user_id" not in session:
                flash("Please log in.", "warning")
                return redirect(url_for("login"))
            if session.get("role") not in roles:
                flash("Access denied.", "danger")
                return redirect(url_for("home"))
            return f(*args, **kwargs)
        return decorated
    return decorator


# ── Core helpers ──────────────────────────────────────────────────────────────

def _compute_risk(selected):
    risk = 0
    for s in selected:
        row = severity_df[severity_df["Symptom"] == s]
        if not row.empty:
            risk += int(row["weight"].values[0])
    return risk


def _enrich_result(top_disease, selected):
    desc = description_df[description_df["Disease"] == top_disease]["Description"].values
    desc = desc[0] if len(desc) > 0 else "No description available."
    prec = precaution_df[precaution_df["Disease"] == top_disease].iloc[:, 1:5].values
    precautions = [p for p in (list(prec[0]) if len(prec) > 0 else [])
                   if isinstance(p, str) and p.strip()]
    doctor = get_doctor_db(top_disease)
    risk   = _compute_risk(selected)
    return desc, precautions, doctor, risk


def _run_prediction(selected, mode):
    """Run ML prediction, save to DB, auto-assign doctor. Returns template context."""
    predictions  = predict_disease(selected)
    top_disease  = predictions[0][0]
    confidence   = get_confidence(predictions)
    desc, precautions, doctor_specialty, risk = _enrich_result(top_disease, selected)
    emergency       = check_emergency(selected)
    user_id         = session.get("user_id")
    profile         = get_patient_profile(user_id) if user_id else None
    city            = profile["city"] if profile else ""
    regional_alerts = get_regional_alerts(city, predictions)

    # Save to DB — save_diagnosis returns the new diagnosis id directly
    skey    = str(uuid.uuid4())
    sid     = create_session(skey, mode, user_id)
    diag_id = save_diagnosis(sid, selected, predictions, risk, doctor_specialty, user_id)

    # Auto-assign to doctor if patient is logged in
    assigned_doctor = None
    if user_id and diag_id:
        doc_uid = auto_assign_doctor(doctor_specialty)
        if doc_uid:
            create_consultation(diag_id, user_id, doc_uid)
            assigned_doctor = get_doctor_profile(doc_uid)

    return dict(
        predictions=predictions, disease=top_disease,
        description=desc, precautions=precautions,
        doctor=doctor_specialty, risk=risk, symptoms=selected,
        confidence=confidence, emergency=emergency,
        regional_alerts=regional_alerts, city=city,
        assigned_doctor=assigned_doctor,
    )


# ── Auth ──────────────────────────────────────────────────────────────────────

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username  = request.form.get("username", "").strip()
        password  = request.form.get("password", "").strip()
        full_name = request.form.get("full_name", "").strip()
        age       = request.form.get("age", "")
        gender    = request.form.get("gender", "")
        city      = request.form.get("city", "").strip()
        if not username or not password or not full_name:
            flash("Username, password and full name are required.", "danger")
            return render_template("register.html")
        uid, err = register_user(username, password)
        if err:
            flash(err, "danger")
            return render_template("register.html")
        save_patient_profile(uid, full_name, age or None, gender or None, city or None)
        flash("Account created! Please log in.", "success")
        return redirect(url_for("login"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        user     = login_user(username, password)
        if not user:
            flash("Invalid username or password.", "danger")
            return render_template("login.html")
        session["user_id"]  = user["id"]
        session["username"] = user["username"]
        session["role"]     = user["role"]
        role = user["role"]
        if role == "doctor": return redirect(url_for("doctor_dashboard"))
        if role == "lab":    return redirect(url_for("lab_dashboard"))
        if role == "admin":  return redirect(url_for("admin_dashboard"))
        flash(f"Welcome back, {user['username']}!", "success")
        return redirect(url_for("home"))
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.", "info")
    return redirect(url_for("login"))


# ── Home & Diagnosis ──────────────────────────────────────────────────────────

@app.route("/")
def home():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("index.html", symptoms=symptom_columns)


@app.route("/predict_form", methods=["POST"])
def predict_form():
    selected = request.form.getlist("symptom")
    if len(selected) < 3:
        return render_template("index.html", symptoms=symptom_columns,
                               error="Please select at least 3 symptoms.")
    ctx = _run_prediction(selected, "form")
    return render_template("result.html", **ctx)


# ── Chatbot ───────────────────────────────────────────────────────────────────

@app.route("/chatbot")
def chatbot():
    return render_template("chatbot.html", phase="start", symptoms=list(symptom_columns))


@app.route("/chat_start", methods=["POST"])
def chat_start():
    raw = request.form.get("first_symptom", "").strip()
    if not raw:
        return render_template("chatbot.html", phase="start",
                               symptoms=list(symptom_columns),
                               error="Please enter your main symptom.")
    first_symptom = parse_free_text(raw)
    cid = str(uuid.uuid4())
    session["chat_id"] = cid
    chatbot_states[cid] = {
        "asked": [first_symptom], "positive": [first_symptom],
        "negative": [], "severity_notes": {}, "step": 1
    }
    q, _ = next_question([first_symptom], [first_symptom], [])
    if q is None:
        # Pick first unasked fallback that isn't the same as the starting symptom
        FALLBACK_POOL = [
            "nausea", "headache", "fever", "chills", "loss_of_appetite",
            "weakness", "fatigue", "dizziness", "cough", "skin_rash",
        ]
        q = next((s for s in FALLBACK_POOL if s != first_symptom), "nausea")
    chatbot_states[cid]["asked"].append(q)
    chatbot_states[cid]["step"] = 2
    sev_q    = get_severity_question(first_symptom)
    sev_opts = get_severity_options(sev_q) if sev_q else []
    possible = get_possible_count([first_symptom], [first_symptom], [])
    return render_template("chatbot.html", phase="chat", question=q,
                           first_symptom=first_symptom, sev_q=sev_q,
                           sev_opts=sev_opts, step=2, possible=possible)


@app.route("/chat_answer", methods=["POST"])
def chat_answer():
    cid   = session.get("chat_id", "default")
    state = chatbot_states.setdefault(cid, {
        "asked": [], "positive": [], "negative": [], "severity_notes": {}, "step": 1
    })
    symptom  = request.form["symptom"]
    ans      = request.form["answer"]
    sev_note = request.form.get("severity_note", "")
    if ans == "yes":
        state["positive"].append(symptom)
        if sev_note:
            state["severity_notes"][symptom] = sev_note
    else:
        state["negative"].append(symptom)
    # Mark this symptom as done BEFORE finding the next question
    # so next_question() never returns the same symptom again
    if symptom not in state["asked"]:
        state["asked"].append(symptom)
    state["step"] = state.get("step", 1) + 1
    q, _     = next_question(state["asked"], state["positive"], state["negative"])
    possible = get_possible_count(state["asked"], state["positive"], state["negative"])
    # If no more useful questions AND enough symptoms → diagnose
    ready = (q is None or len(state["asked"]) > 12) and len(state["positive"]) >= 3
    if ready:
        session["last_severity_notes"] = state.get("severity_notes", {})
        ctx = _run_prediction(state["positive"], "chatbot")
        chatbot_states.pop(cid, None)
        return render_template("result.html", **ctx)

    # Fallback: if next_question returns None but we still need more symptoms,
    # pick the next unasked common symptom — never repeat the same one
    if q is None:
        FALLBACK_POOL = [
            "nausea", "headache", "fever", "chills", "loss_of_appetite",
            "weakness", "dizziness", "sweating", "skin_rash", "back_pain",
            "fatigue", "cough", "breathlessness", "joint_pain", "stomach_pain",
        ]
        q = next(
            (s for s in FALLBACK_POOL if s not in state["asked"] and s not in state["negative"]),
            None
        )
        # If every fallback is exhausted too, just diagnose with what we have
        if q is None:
            session["last_severity_notes"] = state.get("severity_notes", {})
            ctx = _run_prediction(state["positive"] or ["fatigue"], "chatbot")
            chatbot_states.pop(cid, None)
            return render_template("result.html", **ctx)

    state["asked"].append(q)
    sev_q    = get_severity_question(q) if q else None
    sev_opts = get_severity_options(sev_q) if sev_q else []
    msg = ("Please confirm at least 3 symptoms for a better diagnosis."
           if len(state["positive"]) < 3 else None)
    return render_template("chatbot.html", phase="chat", question=q,
                           message=msg, sev_q=sev_q, sev_opts=sev_opts,
                           step=state["step"], possible=possible)


@app.route("/confirm", methods=["POST"])
def confirm():
    disease  = request.form["disease"]
    symptoms = request.form["symptoms"].split(",")
    store_case_db(symptoms, disease, session.get("user_id"))
    return render_template("confirmed.html", disease=disease)


# ── PDF & Email ───────────────────────────────────────────────────────────────

@app.route("/download_report", methods=["POST"])
def download_report():
    disease     = request.form.get("disease", "")
    confidence  = float(request.form.get("confidence", 0))
    risk        = int(request.form.get("risk", 0))
    doctor      = request.form.get("doctor", "")
    symptoms    = request.form.get("symptoms", "").split(",")
    precautions = [p for p in request.form.get("precautions", "").split("|") if p]
    description = request.form.get("description", "")
    city        = request.form.get("city", "")
    try:
        predictions = json.loads(request.form.get("predictions", "[]"))
    except Exception:
        predictions = []
    user_id         = session.get("user_id")
    profile         = get_patient_profile(user_id) if user_id else None
    diary           = get_diary(user_id, 14) if user_id else []
    regional_alerts = get_regional_alerts(city, predictions) if predictions else []
    sev_notes       = session.get("last_severity_notes", {})

    # Fetch assigned doctor from most recent consultation
    assigned_doctor = None
    if user_id:
        consults = get_patient_consultations(user_id)
        if consults:
            latest = consults[0]
            assigned_doctor = get_doctor_profile(latest["doctor_user_id"]) if latest.get("doctor_user_id") else None

    pdf_bytes = generate_report(
        patient_name = profile["full_name"] if profile else session.get("username", "Patient"),
        age          = profile["age"]    if profile else None,
        gender       = profile["gender"] if profile else None,
        city         = profile["city"]   if profile else city,
        disease=disease, confidence=confidence, risk=risk, doctor=doctor,
        symptoms=symptoms, predictions=predictions, precautions=precautions,
        description=description, diary=diary,
        regional_alerts=regional_alerts, severity_notes=sev_notes,
        assigned_doctor=assigned_doctor,
    )
    return Response(pdf_bytes, mimetype="application/pdf",
                    headers={"Content-Disposition":
                             f"attachment; filename=MediAI_{disease.replace(' ', '_')}.pdf"})


@app.route("/send_report", methods=["POST"])
def send_report():
    email       = request.form.get("email", "").strip()
    disease     = request.form.get("disease", "")
    confidence  = float(request.form.get("confidence", 0))
    doctor      = request.form.get("doctor", "")
    risk        = int(request.form.get("risk", 0))
    symptoms    = request.form.get("symptoms", "").split(",")
    precautions = request.form.get("precautions", "").split("|")
    user_id     = session.get("user_id")
    profile     = get_patient_profile(user_id) if user_id else None
    name        = profile["full_name"] if profile else "Patient"
    if not email:
        return jsonify({"ok": False, "msg": "No email provided."})
    try:
        send_diagnosis_email(email, name, disease, confidence, doctor, precautions, risk, symptoms)
        return jsonify({"ok": True, "msg": f"Report sent to {email}"})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


# ── Diary ─────────────────────────────────────────────────────────────────────

@app.route("/diary")
@login_required
def diary():
    user_id = session["user_id"]
    trend   = get_trend_data(user_id, 14)
    entries = get_diary(user_id, 30)
    return render_template("diary.html", trend=trend, entries=entries,
                           symptoms=list(symptom_columns))


@app.route("/diary/log", methods=["POST"])
@login_required
def diary_log():
    user_id  = session["user_id"]
    log_date = request.form.get("log_date", "")
    symptoms = request.form.getlist("symptoms")
    severity = int(request.form.get("severity", 1))
    notes    = request.form.get("notes", "").strip()
    if log_date and symptoms:
        log_symptoms(user_id, log_date, symptoms, severity, notes)
        flash("Symptoms logged successfully!", "success")
    else:
        flash("Please select at least one symptom and a date.", "warning")
    return redirect(url_for("diary"))


# ── Profile ───────────────────────────────────────────────────────────────────

@app.route("/profile")
@login_required
def profile():
    user_id = session["user_id"]
    patient = get_patient_profile(user_id)
    history = get_patient_history(user_id)
    return render_template("profile.html", patient=patient, history=history)


# ── Analytics ─────────────────────────────────────────────────────────────────

@app.route("/analytics")
def analytics():
    days         = request.args.get("days", default=None, type=int)
    summary      = get_stats_summary(days)
    recent       = get_recent_diagnoses(10, days)
    top_symptoms = get_top_symptoms(8)
    disease_dist = get_disease_distribution()
    daily        = get_daily_diagnoses(days or 7)
    return render_template("analytics.html", summary=summary, recent=recent,
                           top_symptoms=top_symptoms, disease_dist=disease_dist,
                           daily=daily, days=days or 7)


@app.route("/api/stats")
def api_stats():
    days = request.args.get("days", default=None, type=int)
    return jsonify({
        "summary":      get_stats_summary(days),
        "top_symptoms": get_top_symptoms(8),
        "disease_dist": get_disease_distribution(),
        "daily":        get_daily_diagnoses(days or 7)
    })


# ── Patient — Consultation views ──────────────────────────────────────────────

@app.route("/my_consultations")
@login_required
def my_consultations():
    return render_template("patient_consultations.html",
                           consultations=get_patient_consultations(session["user_id"]))


@app.route("/consultation/<int:cid>")
@login_required
def view_consultation(cid):
    c = get_consultation(cid)
    if not c or (c["patient_user_id"] != session["user_id"]
                 and session.get("role") not in ("doctor", "admin")):
        flash("Not found or access denied.", "danger")
        return redirect(url_for("home"))
    return render_template("consultation_detail.html", c=c,
                           orders=get_lab_orders_for_consultation(cid))


# ── Doctor ────────────────────────────────────────────────────────────────────

@app.route("/doctor")
@role_required("doctor")
def doctor_dashboard():
    uid = session["user_id"]
    return render_template("doctor_dashboard.html",
                           doc     = get_doctor_profile(uid),
                           pending = get_doctor_consultations(uid, "pending"),
                           active  = get_doctor_consultations(uid, "in_review"),
                           done    = get_doctor_consultations(uid, "completed"),
                           stats   = get_workflow_stats())


@app.route("/doctor/consultation/<int:cid>")
@role_required("doctor")
def doctor_view_consultation(cid):
    c = get_consultation(cid)
    if not c or c["doctor_user_id"] != session["user_id"]:
        flash("Not found.", "danger")
        return redirect(url_for("doctor_dashboard"))
    if c["status"] == "pending":
        update_consultation(cid,
                            c["doctor_notes"] or "",
                            c["final_diagnosis"] or "",
                            c["prescription"] or "",
                            str(c["follow_up_date"]) if c["follow_up_date"] else "",
                            "in_review")
        c["status"] = "in_review"
    return render_template("doctor_consultation.html",
                           c=c,
                           orders=get_lab_orders_for_consultation(cid),
                           lab_tests=LAB_TEST_TYPES)


@app.route("/doctor/consultation/<int:cid>/save", methods=["POST"])
@role_required("doctor")
def doctor_save_consultation(cid):
    c = get_consultation(cid)
    if not c or c["doctor_user_id"] != session["user_id"]:
        flash("Not found.", "danger")
        return redirect(url_for("doctor_dashboard"))
    update_consultation(cid,
                        request.form.get("doctor_notes", ""),
                        request.form.get("final_diagnosis", ""),
                        request.form.get("prescription", ""),
                        request.form.get("follow_up_date", ""),
                        request.form.get("status", "in_review"))
    priority   = request.form.get("priority", "normal")
    test_notes = request.form.get("lab_test_notes", "")
    for test in request.form.getlist("lab_tests"):
        create_lab_order(cid, c["patient_user_id"], session["user_id"],
                         test, test_notes, priority)
    flash("Consultation updated.", "success")
    return redirect(url_for("doctor_view_consultation", cid=cid))


# ── Lab ───────────────────────────────────────────────────────────────────────

@app.route("/lab")
@role_required("lab")
def lab_dashboard():
    uid = session["user_id"]
    return render_template("lab_dashboard.html",
                           lab     = get_lab_profile(uid),
                           pending = get_lab_tech_orders(uid, "pending"),
                           done    = get_lab_tech_orders(uid, "completed"),
                           stats   = get_workflow_stats())


@app.route("/lab/order/<int:oid>", methods=["GET", "POST"])
@role_required("lab")
def lab_submit_result(oid):
    if request.method == "POST":
        submit_lab_result(
            order_id     = oid,
            lab_user_id  = session["user_id"],
            result_text  = request.form.get("result_text", ""),
            result_value = request.form.get("result_value", ""),
            unit         = request.form.get("unit", ""),
            normal_range = request.form.get("normal_range", ""),
            is_abnormal  = int(request.form.get("is_abnormal", 0)),
            remarks      = request.form.get("remarks", ""),
        )
        flash("Result submitted!", "success")
        return redirect(url_for("lab_dashboard"))

    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    cur.execute("""
        SELECT lo.*, p.full_name AS patient_name, p.age, p.gender,
               dp.full_name AS doctor_name, dp.specialty, d.top_disease
        FROM   lab_orders lo
        JOIN   patients        p  ON p.user_id  = lo.patient_user_id
        JOIN   doctor_profiles dp ON dp.user_id = lo.doctor_user_id
        JOIN   consultations   c  ON c.id       = lo.consultation_id
        JOIN   diagnoses       d  ON d.id       = c.diagnosis_id
        WHERE  lo.id = %s AND lo.lab_user_id = %s
    """, (oid, session["user_id"]))
    order = cur.fetchone()
    cur.close(); conn.close()
    if not order:
        flash("Order not found.", "danger")
        return redirect(url_for("lab_dashboard"))
    return render_template("lab_result_form.html", order=order)


# ── Admin ─────────────────────────────────────────────────────────────────────

@app.route("/admin")
@role_required("admin")
def admin_dashboard():
    return render_template("admin_dashboard.html",
                           doctors   = get_all_doctors(),
                           lab_techs = get_all_lab_techs(),
                           stats     = get_workflow_stats())


@app.route("/admin/create_doctor", methods=["POST"])
@role_required("admin")
def admin_create_doctor():
    uid, err = create_doctor(
        request.form.get("username",      "").strip(),
        request.form.get("password",      "").strip(),
        request.form.get("full_name",     "").strip(),
        request.form.get("specialty",     "").strip(),
        request.form.get("qualification", "").strip(),
        int(request.form.get("experience", 0) or 0),
    )
    flash("Doctor created!" if not err else f"Error: {err}",
          "success" if not err else "danger")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete_doctor/<int:uid>", methods=["POST"])
@role_required("admin")
def admin_delete_doctor(uid):
    from workflow import delete_staff
    err = delete_staff(uid, "doctor")
    if err:
        flash(err, "danger")
    else:
        flash("Doctor removed.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete_lab/<int:uid>", methods=["POST"])
@role_required("admin")
def admin_delete_lab(uid):
    from workflow import delete_staff
    err = delete_staff(uid, "lab")
    if err:
        flash(err, "danger")
    else:
        flash("Lab technician removed.", "success")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/create_lab", methods=["POST"])
@role_required("admin")
def admin_create_lab():
    uid, err = create_lab_tech(
        request.form.get("username",  "").strip(),
        request.form.get("password",  "").strip(),
        request.form.get("full_name", "").strip(),
        request.form.get("lab_name",  "Central Lab").strip(),
    )
    flash("Lab technician created!" if not err else f"Error: {err}",
          "success" if not err else "danger")
    return redirect(url_for("admin_dashboard"))


# ── Video Call ───────────────────────────────────────────────────────────────

@app.route("/video/create/<int:cid>", methods=["POST"])
@role_required("doctor")
def create_video_room(cid):
    """Doctor creates a video room for a consultation."""
    import requests as req
    c = get_consultation(cid)
    if not c or c["doctor_user_id"] != session["user_id"]:
        return jsonify({"ok": False, "msg": "Not found."})
    try:
        # Create a Daily.co room
        resp = req.post(
            "https://api.daily.co/v1/rooms",
            headers={"Authorization": f"Bearer {DAILY_API_KEY}"},
            json={
                "name": f"mediai-consult-{cid}",
                "properties": {
                    "exp": int(__import__("time").time()) + 3600,  # expires in 1 hour
                    "enable_chat": True,
                    "enable_screenshare": False,
                    "start_video_off": False,
                    "start_audio_off": False,
                }
            }
        )
        data = resp.json()
        room_url = data.get("url")
        if not room_url:
            return jsonify({"ok": False, "msg": "Could not create room."})
        # Save room URL + timestamp to the consultation
        import datetime
        conn = get_conn()
        cur  = conn.cursor()
        try:
            cur.execute("ALTER TABLE consultations ADD COLUMN video_room_url VARCHAR(255) DEFAULT NULL")
            conn.commit()
        except Exception:
            conn.rollback()
        try:
            cur.execute("ALTER TABLE consultations ADD COLUMN video_started_at DATETIME DEFAULT NULL")
            conn.commit()
        except Exception:
            conn.rollback()
        now_dt = datetime.datetime.now()
        cur.execute(
            "UPDATE consultations SET video_room_url = %s, video_started_at = %s WHERE id = %s",
            (room_url, now_dt, cid)
        )
        conn.commit()
        cur.close(); conn.close()
        # Format timestamp nicely for the response
        formatted = now_dt.strftime("%d %b %Y, %I:%M %p")
        return jsonify({"ok": True, "url": room_url, "started_at": formatted})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})


@app.route("/video/join/<int:cid>")
@login_required
def join_video_room(cid):
    """Patient or doctor joins the video room for a consultation."""
    conn = get_conn()
    cur  = conn.cursor(dictionary=True)
    try:
        cur.execute("SELECT video_room_url, video_started_at FROM consultations WHERE id = %s", (cid,))
        row = cur.fetchone()
    except Exception:
        row = None
    cur.close(); conn.close()
    if not row or not row.get("video_room_url"):
        flash("No video call has been started for this consultation yet.", "warning")
        return redirect(url_for("view_consultation", cid=cid))
    import datetime
    started_at = row.get("video_started_at")
    started_fmt = started_at.strftime("%d %b %Y, %I:%M %p") if started_at else "—"
    return render_template("video_call.html",
                           room_url=row["video_room_url"],
                           cid=cid,
                           started_at=started_fmt,
                           role=session.get("role"))


if __name__ == "__main__":
    app.run(debug=True)