# Quest-Beings

A live **AWS cloud quiz arena**. Players join a timed challenge, answer AWS questions against the clock, and climb a **real-time leaderboard** powered by Redis.

**Live demo:** https://quest-beings.nazath-aws-journey.online

<!-- Add screenshots here: home page, quiz, leaderboard, results -->
<!-- ![Home](docs/home.png) ![Quiz](docs/quiz.png) ![Leaderboard](docs/leaderboard.png) -->

## Features

- Timed multiple-choice AWS questions (15 seconds each)
- Scoring: 100 points per correct answer plus up to 50 speed-bonus points
- **Live leaderboard** that updates every 3 seconds without a page reload
- Daily **streak** tracking
- Sign up with email and password, or **Sign in with Google** (OAuth 2.0 / OpenID Connect) with profile avatars
- **Admin page** to create and end challenges (restricted to allow-listed, Google-verified accounts)
- Responsive dark UI built with Bootstrap 5

## Architecture

```
 Browser
    |  HTTPS (Let's Encrypt certificate)
    v
 Nginx  (reverse proxy, TLS termination, port 80/443)
    |  HTTP on 127.0.0.1:8000
    v
 Gunicorn  (2 workers, managed by systemd)
    |
    v
 Flask app ----> Redis (Docker)   leaderboard, quiz progress, streaks
    |
    +---------> SQLite            users, challenges, questions, attempts
```

All of it runs on a single **AWS EC2** (Ubuntu 24.04) instance with an Elastic IP. DNS for the custom domain is an `A` record that points to the Elastic IP.

### How Redis is used

| Purpose | Redis structure | Key |
|---|---|---|
| Leaderboard | Sorted set (`ZADD`, `ZREVRANGE`) | `lb:<challenge>` |
| In-progress quiz state | Hash with a 1-hour TTL | `quiz:<user>:<challenge>` |
| Streak counter | String with atomic `INCR` | `streak:<user>`, `lastplayed:<user>` |

SQLite is the permanent record. If Redis loses data, the leaderboard is rebuilt from SQLite (`ensure_leaderboard`). Redis operations that must happen together run in a **pipeline**.

## Tech stack

- **Backend:** Python, Flask 3, Flask-SQLAlchemy, Flask-Login
- **Auth:** Authlib (Google OAuth), password hashing with Werkzeug
- **Data:** Redis 8 (Docker), SQLite
- **Frontend:** Jinja templates, Bootstrap 5, vanilla JavaScript
- **Infra:** AWS EC2, Nginx, Gunicorn, systemd, Docker, Let's Encrypt (certbot)
- **Source control:** Git and GitHub, feature branches merged through pull requests

## Run it locally

Requirements: Python 3.11+, Docker.

```bash
# 1. Clone
git clone <your-repo-url>
cd Quest-Beings

# 2. Virtual environment and dependencies
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
python -m pip install -r requirements.txt

# 3. Start Redis
docker run -d --name redis -p 6379:6379 --restart unless-stopped redis

# 4. Configure environment
cp .env.example .env      # then edit the values (see below)

# 5. Seed the first challenge and run
python seed.py
python app.py
```

Open http://localhost:5000.

### Environment variables

| Variable | Description |
|---|---|
| `SECRET_KEY` | Signs session cookies. Use a long random value (`python -c "import secrets; print(secrets.token_hex(32))"`). |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth client from Google Cloud Console. |
| `ADMIN_EMAILS` | Comma-separated emails allowed to use `/admin` (must sign in with Google). |
| `REDIS_URL` | Optional. Defaults to `redis://localhost:6379/0`. |

For Google login, add `http://localhost:5000/auth/google/callback` as an authorized redirect URI in your OAuth client. Never commit `.env`.

## Project structure

```
Quest-Beings/
├── app.py               # Flask app: models, Redis helpers, routes
├── seed.py              # Creates the starter AWS challenge and questions
├── requirements.txt
├── .env.example
└── templates/           # base, home, login, signup, quiz, results, admin, privacy
```

## Deployment notes

1. Launch an Ubuntu EC2 instance. Security group: SSH from my IP only, HTTP and HTTPS open to the world.
2. Install Docker, run Redis with `--restart unless-stopped`, clone the repo and create a virtualenv.
3. Run Gunicorn on `127.0.0.1:8000` under a **systemd** service so it starts on boot and restarts on failure.
4. Put **Nginx** in front as a reverse proxy.
5. Point an `A` record at the Elastic IP, then run `certbot --nginx` for HTTPS and automatic renewal.
6. Flask sits behind a proxy, so `ProxyFix` makes it trust Nginx's `X-Forwarded-*` headers. Without it, OAuth redirect URLs would be built as `http://`.

## Security choices

- Session cookies are signed with `SECRET_KEY` and use `SameSite=Lax`
- Passwords are hashed, never stored in plain text
- Leaderboard JavaScript writes names with `textContent` (no HTML injection)
- Google accounts are never auto-merged into an existing password account
- Admin routes require an allow-listed, Google-verified email
- Secrets live in a `chmod 600` `.env` on the server and are excluded from Git

## What I learned

- Choosing the right Redis data structure for each job (sorted set, hash with TTL, atomic counters)
- Why a reverse proxy and an application server are separate (Nginx and Gunicorn)
- How OAuth 2.0 redirects, DNS records and TLS certificates fit together
- Running a service reliably with systemd, and diagnosing real deploy errors (port conflicts, Docker permissions, blocked packages)

## Roadmap

- [ ] GitHub Actions: deploy to EC2 automatically on merge to `main`
- [ ] Automated tests in CI
- [ ] Rate limiting on login and answer endpoints
- [ ] More question sets and categories

## Author

Built by **Nazath** as a cloud portfolio project.
