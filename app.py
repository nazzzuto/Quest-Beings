import os
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import (LoginManager, UserMixin, login_user,
                         logout_user, login_required)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-only-change-me")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///pulsequest.db"

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"   # where to send people who aren't logged in


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(60), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


with app.app_context():
    db.create_all()   # creates the tables the first time


@app.route("/")
def home():
    challenge = {
        "title": "Python Trivia Blitz",
        "description": "Answer 5 questions as fast as you can. Speed earns bonus points.",
        "seconds_left": 600,
    }
    players = [
        {"name": "Aarav", "score": 120},
        {"name": "Mira", "score": 95},
        {"name": "Nazath", "score": 80},
    ]
    return render_template("home.html", challenge=challenge, players=players)


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
            flash("Welcome to PulseQuest!", "success")
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


@app.route("/join")
@login_required
def join():
    flash("You're in! The quiz arrives in the next PR.", "success")
    return redirect(url_for("home"))


if __name__ == "__main__":
    app.run(debug=True)