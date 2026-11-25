import os
import time
from datetime import datetime, timedelta, timezone

from authlib.integrations.flask_client import OAuth

import redis
from flask import Flask, render_template, redirect, url_for, request, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user,
                         logout_user, login_required, current_user)
from werkzeug.security import generate_password_hash, check_password_hash

from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///pulsequest.db"

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

oauth = OAuth(app)
google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

QUESTION_TIME = 15  # seconds allowed per question


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------- Models ----------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256))        # empty for Google-only users
    google_id = db.Column(db.String(60), unique=True)
    avatar_url = db.Column(db.String(300))


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

r = redis.Redis.from_url(
    os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
    decode_responses=True,   # return normal strings instead of bytes
)

QUIZ_TTL = 60 * 60   # a player's quiz progress expires after 1 hour


def lb_key(challenge_id):
    return f"lb:{challenge_id}"


def quiz_key(user_id, challenge_id):
    return f"quiz:{user_id}:{challenge_id}"


def ensure_leaderboard(challenge_id):
    """If Redis lost the board, rebuild it from the database."""
    key = lb_key(challenge_id)
    if not r.exists(key):
        attempts = Attempt.query.filter_by(challenge_id=challenge_id).all()
        if attempts:
            r.zadd(key, {str(a.user_id): a.score for a in attempts})


def get_top_players(challenge_id, n=10):
    ensure_leaderboard(challenge_id)
    rows = r.zrevrange(lb_key(challenge_id), 0, n - 1, withscores=True)
    ids = [int(uid) for uid, _ in rows]
    names = {}
    if ids:
        names = {u.id: u.name for u in User.query.filter(User.id.in_(ids)).all()}
    return [{"rank": i + 1, "name": names.get(int(uid), "?"), "score": int(score)}
            for i, (uid, score) in enumerate(rows)]


def update_streak(user_id):
    """Count consecutive days a player has finished a challenge."""
    today = utcnow().date()
    last = r.get(f"lastplayed:{user_id}")
    if last == str(today):
        return
    if last == str(today - timedelta(days=1)):
        r.incr(f"streak:{user_id}")
    else:
        r.set(f"streak:{user_id}", 1)
    r.set(f"lastplayed:{user_id}", str(today))


def load_quiz():
    """Return (challenge, progress) for the current user from Redis."""
    challenge = get_active_challenge()
    if not challenge:
        return None, None
    data = r.hgetall(quiz_key(current_user.id, challenge.id))
    if not data:
        return challenge, None
    return challenge, {
        "index": int(data["index"]),
        "score": int(data["score"]),
        "correct": int(data["correct"]),
        "shown_at": float(data["shown_at"]),
    }


# ---------- Pages ----------
@app.route("/")
def home():
    challenge = get_active_challenge()
    players, seconds_left = [], 0
    if challenge:
        seconds_left = max(0, int((challenge.ends_at - utcnow()).total_seconds()))
        players = get_top_players(challenge.id)
    return render_template("home.html", challenge=challenge,
                           seconds_left=seconds_left, players=players)


@app.route("/api/leaderboard")
def api_leaderboard():
    challenge = get_active_challenge()
    return jsonify(get_top_players(challenge.id) if challenge else [])


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

        if user and user.password_hash and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("home"))
        flash("Wrong email or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("home"))

@app.route("/auth/google")
def google_login():
    redirect_uri = url_for("google_callback", _external=True)
    return google.authorize_redirect(redirect_uri)


@app.route("/auth/google/callback")
def google_callback():
    try:
        token = google.authorize_access_token()
    except Exception:
        flash("Google login failed. Please try again.", "danger")
        return redirect(url_for("login"))

    info = token.get("userinfo")
    if not info or not info.get("email") or not info.get("email_verified"):
        flash("Google did not give us a verified email.", "danger")
        return redirect(url_for("login"))

    email = info["email"].lower()
    user = User.query.filter_by(google_id=info["sub"]).first()

    if not user:
        if User.query.filter_by(email=email).first():
            flash("That email already has a password account. Please log in with your password.", "warning")
            return redirect(url_for("login"))
        user = User(name=info.get("name") or email.split("@")[0],
                    email=email, google_id=info["sub"])
        db.session.add(user)

    user.avatar_url = info.get("picture")
    db.session.commit()
    login_user(user)
    flash(f"Welcome, {user.name}!", "success")
    return redirect(url_for("home"))

# ---------- Quiz ----------
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

    key = quiz_key(current_user.id, challenge.id)
    if not r.exists(key):   # new player; otherwise resume where they left off
        r.hset(key, mapping={"index": 0, "score": 0, "correct": 0,
                             "shown_at": time.time()})
        r.expire(key, QUIZ_TTL)
        r.zadd(lb_key(challenge.id), {str(current_user.id): 0}, nx=True)
    return redirect(url_for("quiz"))


@app.route("/quiz")
@login_required
def quiz():
    challenge, state = load_quiz()
    if not state:
        return redirect(url_for("join"))
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
    challenge, state = load_quiz()
    if not state:
        return redirect(url_for("join"))
    questions = challenge.questions
    if state["index"] >= len(questions):
        return redirect(url_for("finish"))

    q = questions[state["index"]]
    choice = request.form.get("choice", "")
    elapsed = time.time() - state["shown_at"]

    points = 0
    if choice == q.correct and elapsed <= QUESTION_TIME + 2:
        points = 100 + int(max(0, QUESTION_TIME - elapsed) / QUESTION_TIME * 50)

    key = quiz_key(current_user.id, challenge.id)
    pipe = r.pipeline()                      # send all commands in one go
    pipe.hincrby(key, "index", 1)
    pipe.hincrby(key, "score", points)
    pipe.hset(key, "shown_at", time.time())
    if points:
        pipe.hincrby(key, "correct", 1)
        pipe.zincrby(lb_key(challenge.id), points, str(current_user.id))
    pipe.execute()

    if state["index"] + 1 >= len(questions):
        return redirect(url_for("finish"))
    return redirect(url_for("quiz"))


@app.route("/quiz/finish")
@login_required
def finish():
    challenge, state = load_quiz()
    if not state:
        return redirect(url_for("home"))
    if state["index"] < len(challenge.questions):
        return redirect(url_for("quiz"))

    exists = Attempt.query.filter_by(
        user_id=current_user.id, challenge_id=challenge.id).first()
    if not exists:
        db.session.add(Attempt(user_id=current_user.id, challenge_id=challenge.id,
                               score=state["score"], correct_count=state["correct"]))
        db.session.commit()
        update_streak(current_user.id)

    r.zadd(lb_key(challenge.id), {str(current_user.id): state["score"]})
    r.delete(quiz_key(current_user.id, challenge.id))
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

    ensure_leaderboard(challenge.id)
    position = r.zrevrank(lb_key(challenge.id), str(current_user.id))
    rank = (position + 1) if position is not None else 1
    return render_template(
        "results.html",
        attempt=attempt,
        rank=rank,
        total_players=r.zcard(lb_key(challenge.id)),
        total_questions=len(challenge.questions),
        streak=int(r.get(f"streak:{current_user.id}") or 0),
    )


if __name__ == "__main__":
    app.run(debug=True)