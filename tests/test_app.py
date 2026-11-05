import os
os.environ["DATABASE_URL"] = "sqlite:///./test.db"

from fastapi.testclient import TestClient
from app.main import app
from app.match import match

client = TestClient(app)


def test_match_scores_and_missing_skills():
    score, missing = match("I know Python and SQL", "Need Python, SQL and Docker")
    assert 0 <= score <= 100
    assert missing == ["docker"]


def test_register_add_and_move_application():
    r = client.post("/register", data={"email": "a@b.com", "password": "password123"}, follow_redirects=False)
    assert r.status_code == 303
    client.post("/profile", data={"cv_text": "Python SQL pytest"})
    client.post("/applications", data={"company": "Acme", "role": "QA Intern", "job_description": "Python, Docker, pytest"})
    page = client.get("/").text
    assert "Acme" in page and "docker" in page
    client.post("/applications/1/status", data={"status": "Interview"})
    assert "Interview" in client.get("/").text


def test_login_rejects_bad_password():
    r = client.post("/login", data={"email": "a@b.com", "password": "wrong"})
    assert r.status_code == 400
