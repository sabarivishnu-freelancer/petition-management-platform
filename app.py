import os
import io
import threading
from datetime import datetime, timezone, timedelta
from flask import Flask, render_template, request, redirect, session, jsonify, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from ai_agent import analyze_petition, find_similar
from reportlab.pdfgen import canvas
from mailer import send_email
from markupsafe import Markup
import logging
import sys
import traceback
from firebase_db import (
    create_user,
    get_user_by_email,
    get_user_by_id,
    get_user_by_username,
    get_all_petitions,
    get_petitions_by_student,
    create_petition,
    get_petition_by_hash,
    get_petition_by_id,
    get_signatures_by_petition,
    get_user_signatures,
    has_user_signed_petition,
    record_signature,
    increment_petition_signature_count,
    update_petition_status,
    delete_petition,
    get_all_users,
    parse_iso_datetime,
    get_ref,
)

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"), override=False)

app = Flask(__name__, static_folder="public/static", template_folder="templates")
app.secret_key = os.getenv("SECRET_KEY", "dev-secret")

# Configure logging so stdout/stderr are captured by Render's logs
logger = logging.getLogger("petition_app")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    sh.setFormatter(fmt)
    logger.addHandler(sh)


@app.errorhandler(Exception)
def handle_exception(e):
    # Log full traceback to stdout (Render captures this in service logs)
    tb = traceback.format_exc()
    logger.exception("Unhandled exception: %s", tb)
    # Also write a local file for quick inspection during debugging
    try:
        with open(os.path.join(os.path.dirname(__file__), "last_error.log"), "a", encoding="utf-8") as fh:
            fh.write("--- %s ---\n" % datetime.utcnow().isoformat())
            fh.write(tb + "\n")
    except Exception:
        logger.exception("Failed to write last_error.log")

    # Return JSON for API requests, otherwise render a friendly error page
    try:
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify({"success": False, "message": "Internal server error"}), 500
    except Exception:
        pass
    return render_template("login.html", error="Internal server error. Try again later."), 500


def nl2br(text):
    if text is None:
        return ''
    return Markup(str(text).replace("\n", "<br>\n"))

app.jinja_env.filters['nl2br'] = nl2br


def login_required(role=None):
    def wrapper(fn):
        from functools import wraps

        @wraps(fn)
        def decorated(*args, **kwargs):
            if not session.get("user_id"):
                return redirect("/")
            if role and session.get("role") != role:
                return redirect("/")
            return fn(*args, **kwargs)

        return decorated

    return wrapper


def petition_to_row(petition):
    if not petition:
        return None
    return (
        petition.get("id"),
        petition.get("title"),
        petition.get("description"),
        petition.get("category"),
        petition.get("priority"),
        petition.get("status"),
        petition.get("signature_count", 0),
        petition.get("student_id"),
        petition.get("created_at"),
    )


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"].strip()
        email = request.form.get("email")
        password = request.form["password"]
        role = request.form.get("role", "student")

        if not username or not password:
            return render_template("register.html", error="Missing fields")

        if get_user_by_username(username) or (email and get_user_by_email(email)):
            return render_template("register.html", error="Username or email already in use")

        hashed = generate_password_hash(password)
        try:
            create_user(username, hashed, email, role)
        except ValueError as e:
            return render_template("register.html", error=str(e))
        except Exception as e:
            return render_template("register.html", error=str(e))

        return redirect("/")

    return render_template("register.html")


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form["username"].strip()
        p = request.form["password"]
        user = get_user_by_username(u)
        if user and check_password_hash(user.get("password", ""), p):
            session["user_id"] = user["id"]
            session["role"] = user.get("role", "student")
            return redirect("/student" if session["role"] == "student" else "/admin")
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/student", methods=["GET", "POST"])
@login_required(role="student")
def student():
    error = None
    if request.method == "POST":
        title = request.form["title"].strip()
        desc = request.form["description"].strip()
        desc = desc.replace('\r\n', '\n').replace('\r', '\n')

        if not title or not desc:
            error = "Title and description are required"
        else:
            existing_petition = get_petition_by_hash(title, desc)
            if existing_petition:
                owner_id = existing_petition.get("student_id")
                if owner_id == session["user_id"]:
                    error = "You have already submitted an identical petition"
                else:
                    error = "A petition with identical title and description already exists"

            if not error:
                existing = get_all_petitions()
                desc_list = [p.get("description", "") for p in existing]
                sim_text, sim_score = find_similar(desc, desc_list, threshold=0.7)
                if sim_text:
                    error = f"A similar petition already exists (score {sim_score:.2f})"

            if not error:
                res = analyze_petition(desc)
                if isinstance(res, tuple) and len(res) == 4:
                    cat, pri, _, _ = res
                else:
                    cat, pri = res
                try:
                    create_petition(title, desc, cat, pri, session["user_id"])
                except Exception as e:
                    error = str(e)

    rows = [petition_to_row(p) for p in get_petitions_by_student(session["user_id"])]
    return render_template("student.html", petitions=rows, error=error)


@app.route("/admin")
@login_required(role="admin")
def admin():
    petitions = sorted(
        get_all_petitions(),
        key=lambda p: (p.get("signature_count", 0), p.get("created_at", "")),
        reverse=True,
    )
    rows = [petition_to_row(p) for p in petitions]
    return render_template("admin.html", petitions=rows)


@app.route("/analytics")
@login_required(role="admin")
def analytics():
    return render_template("analytics.html")


@app.route("/api/analytics/trending")
@login_required(role="admin")
def api_trending_petitions():
    try:
        petitions = get_all_petitions()
        signatures = get_ref("signatures").get() or {}
        cutoff = datetime.utcnow().replace(tzinfo=timezone.utc) - timedelta(days=7)

        data = []
        for p in petitions:
            petition_id = p.get("id")
            petition_sigs = signatures.get(petition_id, {}) or {}
            week_growth = 0
            for signature in petition_sigs.values():
                signed_at = signature.get("signed_at") if isinstance(signature, dict) else None
                dt = parse_iso_datetime(signed_at)
                if dt and dt >= cutoff:
                    week_growth += 1

            data.append({
                "id": petition_id,
                "title": p.get("title"),
                "description": p.get("description"),
                "category": p.get("category"),
                "signature_count": p.get("signature_count", 0),
                "week_growth": week_growth,
                "status": p.get("status"),
                "created_at": p.get("created_at"),
                "growth_rate": "📈 Growing" if week_growth > 0 else "📊 Stable",
            })

        return jsonify({"success": True, "trending": data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/analytics/status-distribution")
@login_required(role="admin")
def api_status_distribution():
    try:
        petitions = get_all_petitions()
        status_dist = {"Pending": 0, "Approved": 0, "Rejected": 0}
        for p in petitions:
            status = p.get("status", "Pending")
            if status in status_dist:
                status_dist[status] += 1

        total = sum(status_dist.values())
        percent_data = {
            status: round((count / total * 100) if total > 0 else 0, 1)
            for status, count in status_dist.items()
        }
        return jsonify({
            "success": True,
            "distribution": status_dist,
            "percentages": percent_data,
            "total": total,
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/analytics/category-breakdown")
@login_required(role="admin")
def api_category_breakdown():
    try:
        petitions = get_all_petitions()
        stats = {}
        for p in petitions:
            category = p.get("category") or "Uncategorized"
            stats.setdefault(category, {"petition_count": 0, "total_signatures": 0})
            stats[category]["petition_count"] += 1
            stats[category]["total_signatures"] += p.get("signature_count", 0)

        data = []
        for category, values in stats.items():
            count = values["petition_count"]
            total_sigs = values["total_signatures"]
            data.append({
                "category": category,
                "petition_count": count,
                "total_signatures": total_sigs,
                "avg_signatures": round(total_sigs / count, 1) if count > 0 else 0,
            })

        data.sort(key=lambda x: x["total_signatures"], reverse=True)
        return jsonify({"success": True, "categories": data})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/analytics/summary")
@login_required(role="admin")
def api_analytics_summary():
    try:
        petitions = get_all_petitions()
        users = get_all_users()

        total_petitions = len(petitions)
        total_signatures = sum(p.get("signature_count", 0) for p in petitions)
        total_students = sum(1 for u in users if u.get("role") == "student")
        avg_signatures = round(total_signatures / total_petitions, 1) if total_petitions > 0 else 0

        category_counts = {}
        for p in petitions:
            category = p.get("category") or "N/A"
            category_counts[category] = category_counts.get(category, 0) + 1

        popular_category = max(category_counts, key=category_counts.get) if category_counts else "N/A"

        return jsonify({
            "success": True,
            "total_petitions": total_petitions,
            "total_signatures": total_signatures,
            "total_students": total_students,
            "avg_signatures_per_petition": avg_signatures,
            "most_popular_category": popular_category,
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/update/<petition_id>/<status>")
@login_required(role="admin")
def update(petition_id, status):
    if status not in ("Approved", "Rejected", "Pending"):
        status = "Pending"

    petition = get_petition_by_id(petition_id)
    if not petition:
        return redirect("/admin")

    update_petition_status(petition_id, status)

    if status == "Rejected":
        def delete_later(pid):
            try:
                delete_petition(pid)
            except Exception:
                pass

        timer = threading.Timer(120, delete_later, args=(petition_id,))
        timer.daemon = True
        timer.start()

    student = get_user_by_id(petition.get("student_id"))
    petition_title = petition.get("title", "Your petition")
    if student and student.get("email"):
        subject = f"Your petition '{petition_title}' status updated"
        body = (
            f"Hello {student.get('username', '')},\n\n"
            f"Your petition '{petition_title}' has been marked as: {status}.\n\n"
            "Regards,\nPetition System"
        )
        try:
            send_email(subject, body, student.get("email"))
        except Exception:
            pass

    signers = get_signatures_by_petition(petition_id)
    if signers:
        subject2 = f"Update on petition '{petition_title}' you signed"
        body2 = (
            "Hello,\n\n"
            f"The petition '{petition_title}' that you signed has been marked as: {status}.\n\n"
            "Regards,\nPetition System"
        )
        for user_id in signers.keys():
            signer = get_user_by_id(user_id)
            if signer and signer.get("email"):
                try:
                    send_email(subject2, body2, signer.get("email"))
                except Exception:
                    pass

    return redirect("/admin")


@app.route("/export/json")
@login_required(role="admin")
def export_json():
    data = []
    for p in get_all_petitions():
        data.append({
            "id": p.get("id"),
            "title": p.get("title"),
            "description": p.get("description"),
            "category": p.get("category"),
            "priority": p.get("priority"),
            "status": p.get("status"),
            "signature_count": p.get("signature_count", 0),
            "student_id": p.get("student_id"),
            "created_at": p.get("created_at"),
        })
    return jsonify(data)


@app.route("/export/pdf")
@login_required(role="admin")
def export_pdf():
    rows = get_all_petitions()
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    y = 800
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(40, y, "Petition Report")
    y -= 20
    pdf.setFont("Helvetica", 10)

    def _norm_desc(text):
        if text:
            return text.replace("\r\n", "\n").replace("\r", "\n")
        return text

    for r in rows:
        title = r.get("title", "")
        description = _norm_desc(r.get("description", ""))
        category = r.get("category", "")
        priority = r.get("priority", "")
        status = r.get("status", "")
        signature_count = r.get("signature_count", 0)
        created_at = r.get("created_at", "")

        pdf.setFont("Helvetica-Bold", 10)
        pdf.drawString(40, y, f"Title: {title}")
        y -= 15
        pdf.setFont("Helvetica", 9)
        max_width = 500
        words = description.split()
        line = ""
        for word in words:
            test_line = line + word + " "
            if pdf.stringWidth(test_line) > max_width:
                if line:
                    pdf.drawString(50, y, line.strip())
                    y -= 12
                line = word + " "
            else:
                line = test_line
        if line:
            pdf.drawString(50, y, line.strip())
            y -= 12

        details = (
            f"Category: {category} | Priority: {priority} | Status: {status} | "
            f"Signatures: {signature_count} | Created: {created_at}"
        )
        pdf.drawString(50, y, details)
        y -= 20
        if y < 60:
            pdf.showPage()
            y = 800
            pdf.setFont("Helvetica", 10)

    pdf.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name="petitions.pdf", mimetype="application/pdf")


@app.route("/browse")
@login_required(role="student")
def browse():
    petitions = sorted(
        get_all_petitions(),
        key=lambda p: (p.get("signature_count", 0), p.get("created_at", "")),
        reverse=True,
    )
    signed_ids = set(get_user_signatures(session["user_id"]).keys())
    rows = [petition_to_row(p) for p in petitions]
    return render_template("browse.html", petitions=rows, signed_ids=signed_ids)


@app.route("/sign/<petition_id>", methods=["POST"])
@login_required(role="student")
def sign_petition(petition_id):
    user_id = session["user_id"]
    if has_user_signed_petition(user_id, petition_id):
        return jsonify({"success": False, "message": "You have already signed this petition"}), 400

    petition = get_petition_by_id(petition_id)
    if not petition:
        return jsonify({"success": False, "message": "Petition not found"}), 404

    try:
        record_signature(user_id, petition_id)
        new_count = increment_petition_signature_count(petition_id)
        return jsonify({"success": True, "message": "Petition signed!", "signature_count": new_count})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/petition/<petition_id>/status")
@login_required(role="student")
def petition_status(petition_id):
    petition = get_petition_by_id(petition_id)
    if not petition:
        return jsonify({"success": False, "message": "Petition not found"}), 404
    is_signed = has_user_signed_petition(session["user_id"], petition_id)
    return jsonify({
        "success": True,
        "id": petition.get("id"),
        "title": petition.get("title"),
        "status": petition.get("status"),
        "signature_count": petition.get("signature_count", 0),
        "priority": petition.get("priority"),
        "category": petition.get("category"),
        "is_signed": is_signed,
    })


@app.route("/petitions/live")
@login_required(role="student")
def petitions_live():
    petitions = sorted(
        get_all_petitions(),
        key=lambda p: p.get("signature_count", 0),
        reverse=True,
    )
    data = []
    for p in petitions:
        data.append({
            "id": p.get("id"),
            "title": p.get("title"),
            "description": p.get("description"),
            "category": p.get("category"),
            "priority": p.get("priority"),
            "status": p.get("status"),
            "signature_count": p.get("signature_count", 0),
            "created_at": p.get("created_at"),
        })
    return jsonify({"success": True, "petitions": data})


if __name__ == "__main__":
    app.run(debug=True)
