# main.py  — Gmail + ICS 自動送信版
# --- CHANGES/ADDITIONS marked with comments "# --- ADDED" or "# --- CHANGED"

import os
import uuid
import logging
import smtplib
from datetime import datetime, timedelta, date, timezone
from zoneinfo import ZoneInfo
from email.message import EmailMessage
from flask import Flask, render_template, request, redirect, url_for
import traceback

from models import db, Candidate, Confirmed, Attendance

def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")

    # --- CHANGED: secret from env optionally
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "fixed-secret-key-abcde-12345")

    # --- CHANGED: DB設定 unchanged, same as before but read from env
    DATABASE_URL = os.environ.get("DATABASE_URL")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL が設定されていません")

    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    # logger
    if not app.debug:
        logging.basicConfig(level=logging.INFO)

    # --- ADDED: Member emails mapping (do NOT pass to templates)
    # Set these in Render / environment:
    # MAIL_MATSUMURA, MAIL_YAMABI, MAIL_YAMANE, MAIL_OKUSAKO, MAIL_KAWASAKI
    MEMBER_EMAILS = {
        "松村": os.environ.get("MAIL_MATSUMURA"),
        "山火": os.environ.get("MAIL_YAMABI"),
        "山根": os.environ.get("MAIL_YAMANE"),
        "奥迫": os.environ.get("MAIL_OKUSAKO"),
        "川崎": os.environ.get("MAIL_KAWASAKI"),
    }

    # --- ADDED: Gmail SMTP settings from env
    SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("GMAIL_USER")   # required
    SMTP_PASS = os.environ.get("GMAIL_PASS")   # required (app password)

    # timezone
    LOCAL_TZ = ZoneInfo(os.environ.get("LOCAL_TZ", "Asia/Tokyo"))

    # ------------------------------
    # Routes (mostly unchanged)
    # ------------------------------
    @app.route("/")
    @app.route("/home")
    def home():
        return render_template("home.html")

    @app.route("/admin")
    def admin_menu():
        return render_template("admin_menu.html")

    @app.route("/candidate", methods=["GET", "POST"])
    def candidate():
        gyms = ["中平井", "平井", "西小岩", "北小岩", "南小岩"]
        times = []
        for h in range(18, 23):
            times.append(f"{h:02d}:00")
            times.append(f"{h:02d}:30")
        times = times[:-1]
        today = datetime.now(tz=LOCAL_TZ)
        base = (today.replace(day=1) + timedelta(days=92)).replace(day=1)
        years = [base.year, base.year + 1]
        months = list(range(1, 13))
        days = list(range(1, 32))
        confirmed_ids = { c.candidate_id for c in Confirmed.query.all() }

        if request.method == "POST":
            cand = Candidate(
                year=int(request.form["year"]),
                month=int(request.form["month"]),
                day=int(request.form["day"]),
                gym=request.form["gym"],
                start=request.form["start"],
                end=request.form["end"]
            )
            db.session.add(cand)
            db.session.commit()
            return render_template("candidate.html",
                                   years=years, months=months, days=days,
                                   gyms=gyms, times=times,
                                   selected_year=cand.year, selected_month=cand.month, selected_day=cand.day,
                                   selected_gym=cand.gym, selected_start=cand.start, selected_end=cand.end,
                                   confirmed_ids=confirmed_ids)

        return render_template("candidate.html",
                               years=years, months=months, days=days,
                               gyms=gyms, times=times,
                               selected_year=base.year, selected_month=base.month, selected_day=base.day,
                               selected_gym="中平井", selected_start="18:00", selected_end="19:00",
                               confirmed_ids=confirmed_ids)

    @app.route("/confirm", methods=["GET", "POST"])
    def confirm():
        candidates = Candidate.query.order_by(
            Candidate.year.asc(), Candidate.month.asc(), Candidate.day.asc(), Candidate.start.asc()
        ).all()
        if request.method == "POST":
            c_id = int(request.form["candidate_id"])
            exists = Confirmed.query.filter_by(candidate_id=c_id).first()
            if not exists:
                db.session.add(Confirmed(candidate_id=c_id))
                db.session.commit()
            return redirect(url_for("confirm"))
        confirmed = (
            db.session.query(Confirmed, Candidate)
            .join(Candidate, Confirmed.candidate_id == Candidate.id)
            .order_by(Candidate.year.asc(), Candidate.month.asc(), Candidate.day.asc(), Candidate.start.asc())
            .all()
        )
        confirmed_list = db.session.query(Confirmed).all()
        confirmed_ids = [c.candidate_id for c in confirmed_list]

        def format_candidate(c):
            d = date(c.year, c.month, c.day)
            youbi = ["月","火","水","木","金","土","日"][d.weekday()]
            return {"id": c.id, "gym": c.gym, "start": c.start, "end": c.end, "md": f"{c.month}/{c.day}（{youbi}）"}
        candidates_fmt = [format_candidate(c) for c in candidates]
        confirmed_fmt = []
        for cnf, c in confirmed:
            d = date(c.year, c.month, c.day)
            youbi = ["月","火","水","木","金","土","日"][d.weekday()]
            confirmed_fmt.append((cnf, {"gym": c.gym, "start": c.start, "end": c.end, "md": f"{c.month}/{c.day}（{youbi}）"}))
        return render_template("confirm.html", candidates=candidates_fmt, confirmed=confirmed_fmt, confirmed_ids=confirmed_ids)

    @app.route("/confirm/<int:candidate_id>/unconfirm", methods=["POST"])
    def unconfirm(candidate_id):
        conf = Confirmed.query.filter_by(candidate_id=candidate_id).first()
        if conf:
            db.session.delete(conf)
            db.session.commit()
        return redirect(url_for("confirm"))

    @app.route("/register", methods=["GET"])
    def register():
        candidates = Candidate.query.order_by(
            Candidate.year.asc(), Candidate.month.asc(), Candidate.day.asc(), Candidate.start.asc()
        ).all()
        return render_template("register_select.html", candidates=candidates)

    # --- CHANGED: register_event — on POST send ICS to member's Gmail if status == "参加"
    @app.route("/register/event/<int:candidate_id>", methods=["GET", "POST"])
    def register_event(candidate_id):
        candidate = Candidate.query.get_or_404(candidate_id)

        event = Confirmed.query.filter_by(candidate_id=candidate_id).first()
        if not event:
            event = Confirmed(candidate_id=candidate_id)
            db.session.add(event)
            db.session.commit()

        members = ["松村", "山火", "山根", "奥迫", "川崎"]

        if request.method == "POST":
            name = request.form["name"]
            status = request.form["status"]

            # Save attendance (do not store email in DB)
            att = Attendance(event_id=event.id, name=name, status=status)
            db.session.add(att)
            db.session.commit()

            # If status is "参加", find server-side email and send .ics via Gmail
            if status == "参加":
                recipient_email = MEMBER_EMAILS.get(name)
                if recipient_email:
                    try:
                        send_ics_via_gmail(candidate, recipient_name=name, recipient_email=recipient_email,
                                           smtp_user=SMTP_USER, smtp_pass=SMTP_PASS,
                                           smtp_server=SMTP_SERVER, smtp_port=SMTP_PORT,
                                           local_tz=LOCAL_TZ)
                    except Exception as e:
                        app.logger.error("ICS send failed: %s", e)
                        app.logger.error(traceback.format_exc())  # ← これを追加！
                        # Do not block attendance registration on send failure
            
            return redirect(url_for("register"))

        attendance = Attendance.query.filter_by(event_id=event.id).all()
        return render_template("register_form.html", candidate=candidate, attendance=attendance, members=members)

    @app.route("/candidate/<int:id>/edit", methods=["GET", "POST"])
    def edit_candidate(id):
        cand = Candidate.query.get_or_404(id)
        gyms = ["中平井", "平井", "西小岩", "北小岩", "南小岩"]
        times = []
        for h in range(18, 23):
            times.append(f"{h:02d}:00")
            times.append(f"{h:02d}:30")
        times = times[:-1]
        if request.method == "POST":
            cand.year = int(request.form["year"])
            cand.month = int(request.form["month"])
            cand.day = int(request.form["day"])
            cand.gym = request.form["gym"]
            cand.start = request.form["start"]
            cand.end = request.form["end"]
            db.session.commit()
            return redirect(url_for("confirm"))
        return render_template("edit_candidate.html", cand=cand, gyms=gyms, times=times)

    @app.route("/candidate/<int:id>/delete", methods=["POST"])
    def delete_candidate(id):
        cand = Candidate.query.get_or_404(id)
        Attendance.query.filter(
            Attendance.event_id.in_(
                db.session.query(Confirmed.id).filter_by(candidate_id=id)
            )
        ).delete(synchronize_session=False)
        Confirmed.query.filter_by(candidate_id=id).delete()
        db.session.delete(cand)
        db.session.commit()
        return redirect(url_for("admin_menu"))

    @app.route("/attendance/<int:id>/edit", methods=["GET", "POST"])
    def edit_attendance(id):
        att = Attendance.query.get_or_404(id)
        members = ["松村", "山火", "山根", "奥迫", "川崎"]
        if request.method == "POST":
            att.name = request.form["name"]
            att.status = request.form["status"]
            db.session.commit()
            return redirect(url_for("register_event", candidate_id=att.event.candidate_id))
        return render_template("edit_attendance.html", att=att, members=members)

    @app.route("/attendance/<int:id>/delete", methods=["POST"])
    def delete_attendance(id):
        att = Attendance.query.get_or_404(id)
        candidate_id = att.event.candidate_id
        db.session.delete(att)
        db.session.commit()
        return redirect(url_for("register_event", candidate_id=candidate_id))

    # --- ADDED: ICS creation and Gmail send function
    def make_ics(summary, description, location, dtstart_local: datetime, dtend_local: datetime, uid=None):
        """
        Create ICS string. Input datetimes must be timezone-aware in local tz.
        We convert to UTC and produce Z-suffixed timestamps (widely compatible).
        """
        if uid is None:
            uid = f"{uuid.uuid4()}@yourapp.local"

        dtstart_utc = dtstart_local.astimezone(timezone.utc)
        dtend_utc = dtend_local.astimezone(timezone.utc)
        dtstamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        dtstart_str = dtstart_utc.strftime("%Y%m%dT%H%M%SZ")
        dtend_str = dtend_utc.strftime("%Y%m%dT%H%M%SZ")

        def esc(s: str):
            return s.replace("\\", "\\\\").replace("\n", "\\n").replace(",", "\\,").replace(";", "\\;")

        s = esc(summary); d = esc(description); l = esc(location)

        ics = (
            "BEGIN:VCALENDAR\r\n"
            "PRODID:-//YourApp//EN\r\n"
            "VERSION:2.0\r\n"
            "CALSCALE:GREGORIAN\r\n"
            "METHOD:REQUEST\r\n"
            "BEGIN:VEVENT\r\n"
            f"UID:{uid}\r\n"
            f"DTSTAMP:{dtstamp}\r\n"
            f"DTSTART:{dtstart_str}\r\n"
            f"DTEND:{dtend_str}\r\n"
            f"SUMMARY:{s}\r\n"
            f"DESCRIPTION:{d}\r\n"
            f"LOCATION:{l}\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        return ics

    def make_google_calendar_link(title, details, location, start_local: datetime, end_local: datetime):
        """
        Create a Google Calendar 'quick add' link (prefilled event).
        Format for dates: YYYYMMDDTHHMMSSZ or local with timezone? We use UTC times with Z.
        Note: Google expects ISO without separators: 20250110T090000Z
        """
        start_utc = start_local.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        end_utc = end_local.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = "https://www.google.com/calendar/render?action=TEMPLATE"
        from urllib.parse import quote_plus
        params = (
            f"&text={quote_plus(title)}"
            f"&details={quote_plus(details)}"
            f"&location={quote_plus(location)}"
            f"&dates={start_utc}/{end_utc}"
        )
        return base + params

    def send_ics_via_gmail(candidate_obj, recipient_name, recipient_email, smtp_user, smtp_pass, smtp_server="smtp.gmail.com", smtp_port=587, local_tz=LOCAL_TZ):
        """Generate ICS and send via Gmail SMTP with text/calendar attachment and an HTML email containing Google Calendar link."""
        if not smtp_user or not smtp_pass:
            raise RuntimeError("GMAIL_USER/GMAIL_PASS not set")

        # compose datetimes
        y, m, d = candidate_obj.year, candidate_obj.month, candidate_obj.day
        sh, smi = map(int, candidate_obj.start.split(":"))
        eh, emi = map(int, candidate_obj.end.split(":"))
        dtstart_local = datetime(y, m, d, sh, smi, tzinfo=local_tz)
        dtend_local = datetime(y, m, d, eh, emi, tzinfo=local_tz)

        title = f"{candidate_obj.gym} 練習"
        description = f"{recipient_name} さんが参加登録しました。\n場所: {candidate_obj.gym}\n時間: {candidate_obj.start} - {candidate_obj.end}"
        location = candidate_obj.gym

        ics_text = make_ics(title, description, location, dtstart_local, dtend_local, uid=f"{uuid.uuid4()}@yourapp.local")

        # Prepare email bodies
        plain = (
            f"{recipient_name} 様\n\n"
            "参加登録ありがとうございます。\n"
            "添付の .ics を開くか、下のリンクから Google カレンダーに追加してください。\n\n"
            f"イベント: {title}\n場所: {location}\n時間: {candidate_obj.start} - {candidate_obj.end}\n\n"
            "よろしくお願いします。"
        )

        gcal_link = make_google_calendar_link(title, description, location, dtstart_local, dtend_local)
        html = (
            f"<p>{recipient_name} 様</p>"
            f"<p>参加登録ありがとうございます。以下の方法でカレンダーに追加できます：</p>"
            f"<ol>"
            f"<li>添付の <strong>invite.ics</strong> をダブルクリックして追加（Outlook/Google 等でインポート）</li>"
            f"<li><a href=\"{gcal_link}\">Google カレンダーに追加する（ブラウザで開きます）</a></li>"
            f"</ol>"
            f"<p>イベント: <strong>{title}</strong><br>場所: {location}<br>時間: {candidate_obj.start} - {candidate_obj.end}</p>"
            f"<p>よろしくお願いします。</p>"
        )

        # Build EmailMessage
        msg = EmailMessage()
        msg["Subject"] = f"[予定] {title} ({candidate_obj.year}/{candidate_obj.month}/{candidate_obj.day})"
        msg["From"] = smtp_user
        msg["To"] = recipient_email
        msg.set_content(plain)
        msg.add_alternative(html, subtype="html")

        # Attach ICS as text/calendar; method=REQUEST
        ics_bytes = ics_text.encode("utf-8")
        # email.message's add_attachment with maintype/subtype for text/calendar:
        msg.add_attachment(
            ics_bytes,
            maintype="text",
            subtype="calendar",
            filename="invite.ics",
            headers=[
                ("Content-Type", 'text/calendar; method=REQUEST; charset="utf-8"')
            ]
        )

        # Send via SMTP
        with smtplib.SMTP(smtp_server, smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(smtp_user, smtp_pass)
            smtp.send_message(msg)

    # DB create
    with app.app_context():
        db.create_all()

    return app

app = create_app()
