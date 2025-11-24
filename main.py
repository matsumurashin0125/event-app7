import os
from flask import Flask, render_template, request, redirect, url_for, session
from datetime import datetime, timedelta
from models import db, Candidate, Confirmed, Attendance


def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")

    # セッションキー（固定値でOK）
    app.config["SECRET_KEY"] = "fixed-secret-key-abcde-12345"

    # DB設定
    DATABASE_URL = os.environ.get("DATABASE_URL")
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL が設定されていません")

    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)

    # ------------------------------
    # トップページ
    # ------------------------------
    @app.route("/")
    @app.route("/home")
    def home():
        return render_template("home.html")

    # ------------------------------
    # 管理者メニュー（認証なし）
    # ------------------------------
    @app.route("/admin")
    def admin_menu():
        return render_template("admin_menu.html")

    # ------------------------------
    # 候補日入力ページ（認証なし）
    # ------------------------------
    
    @app.route("/candidate", methods=["GET", "POST"])
    def candidate():
        gyms = ["中平井", "平井", "西小岩", "北小岩", "南小岩"]
    
        # 時刻一覧
        times = []
        for h in range(18, 23):
            times.append(f"{h:02d}:00")
            times.append(f"{h:02d}:30")
        times = times[:-1]
    
        # 初期日付
        today = datetime.today()
        base = (today.replace(day=1) + timedelta(days=92)).replace(day=1)
    
        years = [base.year, base.year + 1]
        months = list(range(1, 13))
        days = list(range(1, 32))
    
        # ▼ 追加：確定済み Candidate の ID を取得
        confirmed_ids = {
            c.candidate_id for c in Confirmed.query.all()
        }
    
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
    
            return render_template(
                "candidate.html",
                years=years, months=months, days=days,
                gyms=gyms, times=times,
                selected_year=cand.year,
                selected_month=cand.month,
                selected_day=cand.day,
                selected_gym=cand.gym,
                selected_start=cand.start,
                selected_end=cand.end,
                # ▼ 追加
                confirmed_ids=confirmed_ids
            )
    
        return render_template(
            "candidate.html",
            years=years, months=months, days=days,
            gyms=gyms, times=times,
            selected_year=base.year,
            selected_month=base.month,
            selected_day=base.day,
            selected_gym="中平井",
            selected_start="18:00",
            selected_end="19:00",
            # ▼ 追加
            confirmed_ids=confirmed_ids
        )


    # ------------------------------
    # 日程確定（認証なし）
    # ------------------------------
    @app.route("/confirm", methods=["GET", "POST"])
    def confirm():
        candidates = Candidate.query.order_by(
            Candidate.year.asc(),
            Candidate.month.asc(),
            Candidate.day.asc(),
            Candidate.start.asc()
        ).all()
    
        if request.method == "POST":
            c_id = int(request.form["candidate_id"])
            exists = Confirmed.query.filter_by(candidate_id=c_id).first()
    
            if not exists:
                db.session.add(Confirmed(candidate_id=c_id))
                db.session.commit()
    
            return redirect(url_for("confirm"))
    
        # 確定済み情報
        confirmed = (
            db.session.query(Confirmed, Candidate)
            .join(Candidate, Confirmed.candidate_id == Candidate.id)
            .order_by(
                Candidate.year.asc(),
                Candidate.month.asc(),
                Candidate.day.asc(),
                Candidate.start.asc()
            )
            .all()
        )
    
        # 確定済みIDリスト
        confirmed_list = db.session.query(Confirmed).all()
        confirmed_ids = [c.candidate_id for c in confirmed_list]
    
        # -----------------------------
        # 候補日を月/日（曜）付きに整形
        # -----------------------------
        def format_candidate(c):
            d = datetime.date(c.year, c.month, c.day)
            youbi = ["月","火","水","木","金","土","日"][d.weekday()]
            return {
                "id": c.id,
                "gym": c.gym,
                "start": c.start,
                "end": c.end,
                "md": f"{c.month}/{c.day}（{youbi}）"
            }
    
        candidates_fmt = [format_candidate(c) for c in candidates]
    
        confirmed_fmt = []
        for cnf, c in confirmed:
            d = datetime.date(c.year, c.month, c.day)
            youbi = ["月","火","水","木","金","土","日"][d.weekday()]
            confirmed_fmt.append((cnf, {
                "gym": c.gym,
                "start": c.start,
                "end": c.end,
                "md": f"{c.month}/{c.day}（{youbi}）"
            }))
    
        return render_template(
            "confirm.html",
            candidates=candidates_fmt,
            confirmed=confirmed_fmt,
            confirmed_ids=confirmed_ids
        )

    # ------------------------------
    # 確定取消し
    # ------------------------------
    @app.route("/confirm/<int:candidate_id>/unconfirm", methods=["POST"])
    def unconfirm(candidate_id):
        conf = Confirmed.query.filter_by(candidate_id=candidate_id).first()
        if conf:
            db.session.delete(conf)
            db.session.commit()
        return redirect(url_for("confirm"))

    # ------------------------------
    # 参加登録（カード方式）
    # ------------------------------
    @app.route("/register", methods=["GET"])
    def register():
        candidates = Candidate.query.order_by(
            Candidate.year.asc(),
            Candidate.month.asc(),
            Candidate.day.asc(),
            Candidate.start.asc()
        ).all()
        return render_template("register_select.html", candidates=candidates)

    # ------------------------------
    # 参加登録フォーム
    # ------------------------------
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
            att = Attendance(
                event_id=event.id,
                name=request.form["name"],
                status=request.form["status"]
            )
            db.session.add(att)
            db.session.commit()

            return redirect(url_for("register"))

        attendance = Attendance.query.filter_by(event_id=event.id).all()

        return render_template(
            "register_form.html",
            candidate=candidate,
            attendance=attendance,
            members=members
        )

    # ------------------------------
    # 候補日編集
    # ------------------------------
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

    # ------------------------------
    # 候補日削除
    # ------------------------------
    @app.route("/candidate/<int:id>/delete", methods=["POST"])
    def delete_candidate(id):
        cand = Candidate.query.get_or_404(id)
    
        # ① Attendance を先に削除
        # Attendance → Confirmed (event_id) → Candidate
        Attendance.query.filter(
            Attendance.event_id.in_(
                db.session.query(Confirmed.id).filter_by(candidate_id=id)
            )
        ).delete(synchronize_session=False)
    
        # ② Confirmed を削除
        Confirmed.query.filter_by(candidate_id=id).delete()
    
        # ③ Candidate を削除
        db.session.delete(cand)
        db.session.commit()
    
        return redirect(url_for("admin_menu"))


    # ------------------------------
    # 出欠編集
    # ------------------------------
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

    # ------------------------------
    # 出欠削除
    # ------------------------------
    @app.route("/attendance/<int:id>/delete", methods=["POST"])
    def delete_attendance(id):
        att = Attendance.query.get_or_404(id)
        candidate_id = att.event.candidate_id

        db.session.delete(att)
        db.session.commit()

        return redirect(url_for("register_event", candidate_id=candidate_id))

    # DB作成
    with app.app_context():
        db.create_all()

    return app


app = create_app()
