import os
import time
from datetime import datetime, timedelta, timezone

from flask import Flask, render_template, redirect, url_for, request, flash, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user,
                         logout_user, login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///pulsequest.db"

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

QUESTION_TIME = 15  # seconds allowed per question


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------- Models ----------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)


class Challenge(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.String(300), nullable=False)
    ends_at = db.Column(db.DateTime, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    questions = db.relationship("Question", backref="challenge",
                                order_by="Question.id")


class Question(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    challenge_id = db.Column(db.Integer, db.ForeignKey("challenge.id"), nullable=False)
    text = db.Column(db.String(300), nullable=False)
    option_a = db.Column(db.String(150), nullable=False)
    option_b = db.Column(db.String(150), nullable=False)
    option_c = db.Column(db.String(150), nullable=False)
    option_d = db.Column(db.String(150), nullable=False)
    correct = db.Column(db.String(1), nullable=False)  # "a", "b", "c" or "d"

    def options(self):
        return {"a": self.option_a, "b": self.option_b,
                "c": self.option_c, "d": self.option_d}


class Attempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    challenge_id = db.Column(db.Integer, db.ForeignKey("challenge.id"), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    correct_count = db.Column(db.Integer, nullable=False)
    finished_at = db.Column(db.DateTime, default=utcnow)
    user = db.relationship("User")
    __table_args__ = (db.UniqueConstraint("user_id", "challenge_id"),)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


with app.app_context():
    db.create_all()


def get_active_challenge():
    return Challenge.query.filter_by(is_active=True).order_by(Challenge.id.desc()).first()


# ---------- Pages ----------
@app.route("/")
def home():
    challenge = get_active_challenge()
    players, seconds_left = [], 0
    if challenge:
        seconds_left = max(0, int((challenge.ends_at - utcnow()).total_seconds()))
        top = (Attempt.query.filter_by(challenge_id=challenge.id)
               .order_by(Attempt.score.desc()).limit(5).all())
        players = [{"name": a.user.name, "score": a.score} for a in top]
    return render_template("home.html", challenge=challenge,
                           seconds_left=seconds_left, players=players)


# ---------- Auth ----------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form["name"].strip()
        email = request.form["email"].strip().lower()
        password = request.form["password"]

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "danger")
        elif User.query.filter_by(email=email).first():
            flash("That email is already registered.", "danger")
        else:
            user = User(name=name, email=email,
                        password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Welcome to Quest-Beings!", "success")
            return redirect(url_for("home"))
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"].strip().lower()
        password = request.form["password"]
        user = User.query.filter_by(email=email).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("home"))
        flash("Wrong email or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("home"))


# ---------- Quiz ----------
@app.route("/join")
@login_required
def join():
    challenge = get_active_challenge()
    if not challenge or challenge.ends_at <= utcnow():
        flash("There is no live challenge right now.", "warning")
        return redirect(url_for("home"))

    already_played = Attempt.query.filter_by(
        user_id=current_user.id, challenge_id=challenge.id).first()
    if already_played:
        return redirect(url_for("results"))

    state = session.get("quiz")
    if state and state["challenge_id"] == challenge.id:
        return redirect(url_for("quiz"))   # resume, don't restart

    session["quiz"] = {"challenge_id": challenge.id, "index": 0,
                       "score": 0, "correct": 0, "shown_at": time.time()}
    return redirect(url_for("quiz"))


@app.route("/quiz")
@login_required
def quiz():
    state = session.get("quiz")
    if not state:
        return redirect(url_for("join"))
    challenge = db.session.get(Challenge, state["challenge_id"])
    questions = challenge.questions
    if state["index"] >= len(questions):
        return redirect(url_for("finish"))

    elapsed = time.time() - state["shown_at"]
    return render_template(
        "quiz.html",
        q=questions[state["index"]],
        number=state["index"] + 1,
        total=len(questions),
        seconds_left=max(0, int(QUESTION_TIME - elapsed)),
        score=state["score"],
    )


@app.route("/quiz/answer", methods=["POST"])
@login_required
def answer():
    state = session.get("quiz")
    if not state:
        return redirect(url_for("join"))
    challenge = db.session.get(Challenge, state["challenge_id"])
    questions = challenge.questions
    if state["index"] >= len(questions):
        return redirect(url_for("finish"))

    q = questions[state["index"]]
    choice = request.form.get("choice", "")
    elapsed = time.time() - state["shown_at"]   # measured on the server

    if choice == q.correct and elapsed <= QUESTION_TIME + 2:
        bonus = int(max(0, QUESTION_TIME - elapsed) / QUESTION_TIME * 50)
        state["score"] += 100 + bonus
        state["correct"] += 1

    state["index"] += 1
    state["shown_at"] = time.time()
    session["quiz"] = state

    if state["index"] >= len(questions):
        return redirect(url_for("finish"))
    return redirect(url_for("quiz"))


@app.route("/quiz/finish")
@login_required
def finish():
    state = session.get("quiz")
    if not state:
        return redirect(url_for("home"))
    challenge = db.session.get(Challenge, state["challenge_id"])
    if state["index"] < len(challenge.questions):
        return redirect(url_for("quiz"))       # not finished yet

    session.pop("quiz")
    exists = Attempt.query.filter_by(
        user_id=current_user.id, challenge_id=challenge.id).first()
    if not exists:
        db.session.add(Attempt(user_id=current_user.id, challenge_id=challenge.id,
                               score=state["score"], correct_count=state["correct"]))
        db.session.commit()
    return redirect(url_for("results"))


@app.route("/results")
@login_required
def results():
    challenge = get_active_challenge()
    attempt = None
    if challenge:
        attempt = Attempt.query.filter_by(
            user_id=current_user.id, challenge_id=challenge.id).first()
    if not attempt:
        return redirect(url_for("home"))

    rank = Attempt.query.filter(Attempt.challenge_id == challenge.id,
                                Attempt.score > attempt.score).count() + 1
    total_players = Attempt.query.filter_by(challenge_id=challenge.id).count()
    return render_template("results.html", attempt=attempt, rank=rank,
                           total_players=total_players,
                           total_questions=len(challenge.questions))


if __name__ == "__main__":
    app.run(debug=True)