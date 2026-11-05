import hashlib
import hmac
import os
import secrets
from collections import Counter
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from app.match import match

BASE = Path(__file__).resolve().parent
DB_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE.parent / 'interntrack.db'}")
if DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql+psycopg2://", 1)
elif DB_URL.startswith("postgresql://"):
    DB_URL = DB_URL.replace("postgresql://", "postgresql+psycopg2://", 1)
STATUSES = ["Applied", "Interview", "Offer", "Rejected"]

engine = create_engine(DB_URL, connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {})
Session = sessionmaker(bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    pw_hash = Column(String, nullable=False)
    cv_text = Column(Text, default="")


class Application(Base):
    __tablename__ = "applications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    company = Column(String, nullable=False)
    role = Column(String, nullable=False)
    status = Column(String, default="Applied")
    job_description = Column(Text, default="")
    score = Column(Integer, nullable=True)
    missing = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


Base.metadata.create_all(engine)

app = FastAPI(title="JobTrack")
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SECRET_KEY", "dev-secret-change-me"))
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


def hash_pw(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${digest}"


def check_pw(password, stored):
    salt, _ = stored.split("$")
    return hmac.compare_digest(hash_pw(password, salt), stored)


def current_user(request, db):
    uid = request.session.get("uid")
    return db.get(User, uid) if uid else None


def go(path):
    return RedirectResponse(path, status_code=303)


@app.get("/")
def home(request: Request):
    db = Session()
    try:
        if not current_user(request, db):
            return go("/login")
        apps = db.query(Application).order_by(Application.created_at.desc()).filter(
            Application.user_id == request.session["uid"]).all()
        user = current_user(request, db)
        total = len(apps)
        responded = sum(1 for a in apps if a.status != "Applied")
        scores = [a.score for a in apps if a.score is not None]
        gaps = Counter(s for a in apps for s in a.missing.split(",") if s)
        stats = {
            "total": total,
            "interviews": sum(1 for a in apps if a.status == "Interview"),
            "offers": sum(1 for a in apps if a.status == "Offer"),
            "response_rate": round(100 * responded / total) if total else 0,
            "avg_match": round(sum(scores) / len(scores)) if scores else None,
        }
        board = {s: [a for a in apps if a.status == s] for s in STATUSES}
        return templates.TemplateResponse(request, "dashboard.html", {
            "user": user, "stats": stats, "board": board, "gaps": gaps.most_common(6),
            "has_cv": bool(user.cv_text.strip()), "statuses": STATUSES,
        })
    finally:
        db.close()


@app.get("/register")
def register_page(request: Request):
    return templates.TemplateResponse(request, "auth.html", {"mode": "register", "error": None})


@app.post("/register")
def register(request: Request, email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    db = Session()
    try:
        error = None
        if "@" not in email:
            error = "Enter a valid email address."
        elif len(password) < 8:
            error = "Use a password with at least 8 characters."
        elif db.query(User).filter_by(email=email).first():
            error = "An account with this email already exists."
        if error:
            return templates.TemplateResponse(request, "auth.html", {"mode": "register", "error": error}, status_code=400)
        user = User(email=email, pw_hash=hash_pw(password))
        db.add(user)
        db.commit()
        request.session["uid"] = user.id
        return go("/profile")
    finally:
        db.close()


@app.get("/login")
def login_page(request: Request):
    return templates.TemplateResponse(request, "auth.html", {"mode": "login", "error": None})


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    db = Session()
    try:
        user = db.query(User).filter_by(email=email.strip().lower()).first()
        if not user or not check_pw(password, user.pw_hash):
            return templates.TemplateResponse(request, "auth.html", {"mode": "login", "error": "Email or password is incorrect."}, status_code=400)
        request.session["uid"] = user.id
        return go("/")
    finally:
        db.close()


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return go("/login")


@app.get("/profile")
def profile_page(request: Request):
    db = Session()
    try:
        user = current_user(request, db)
        if not user:
            return go("/login")
        return templates.TemplateResponse(request, "profile.html", {"user": user, "saved": request.query_params.get("saved")})
    finally:
        db.close()


@app.post("/profile")
def profile_save(request: Request, cv_text: str = Form("")):
    db = Session()
    try:
        user = current_user(request, db)
        if not user:
            return go("/login")
        user.cv_text = cv_text
        for a in db.query(Application).filter_by(user_id=user.id):
            if a.job_description:
                score, missing = match(cv_text, a.job_description)
                a.score, a.missing = score, ",".join(missing)
        db.commit()
        return go("/profile?saved=1")
    finally:
        db.close()


@app.post("/applications")
def add_application(request: Request, company: str = Form(...), role: str = Form(...), job_description: str = Form("")):
    db = Session()
    try:
        user = current_user(request, db)
        if not user:
            return go("/login")
        score, missing = match(user.cv_text or "", job_description)
        db.add(Application(user_id=user.id, company=company.strip(), role=role.strip(),
                           job_description=job_description, score=score, missing=",".join(missing)))
        db.commit()
        return go("/")
    finally:
        db.close()


@app.post("/applications/{app_id}/status")
def update_status(request: Request, app_id: int, status: str = Form(...)):
    db = Session()
    try:
        a = db.get(Application, app_id)
        if a and a.user_id == request.session.get("uid") and status in STATUSES:
            a.status = status
            db.commit()
        return go("/")
    finally:
        db.close()


@app.post("/applications/{app_id}/delete")
def delete_application(request: Request, app_id: int):
    db = Session()
    try:
        a = db.get(Application, app_id)
        if a and a.user_id == request.session.get("uid"):
            db.delete(a)
            db.commit()
        return go("/")
    finally:
        db.close()
