import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

SKILLS = [
    "python", "java", "javascript", "typescript", "c++", "c#", "sql", "html", "css",
    "react", "node.js", "django", "flask", "fastapi", "spring", "git", "github", "docker",
    "kubernetes", "aws", "azure", "linux", "rest", "api", "postgresql", "mysql", "mongodb",
    "pandas", "numpy", "scikit-learn", "tensorflow", "pytorch", "machine learning",
    "deep learning", "nlp", "data analysis", "data visualization", "power bi", "tableau",
    "excel", "statistics", "pytest", "selenium", "playwright", "test automation",
    "manual testing", "qa", "ci/cd", "agile", "scrum", "jira", "postman", "communication",
    "teamwork", "problem solving",
]


def extract_skills(text):
    t = text.lower()
    return {s for s in SKILLS if re.search(r"(?<![a-z0-9])" + re.escape(s) + r"(?![a-z0-9])", t)}


def match(cv, jd):
    """Return (score 0-100 or None, list of missing skills)."""
    if not cv.strip() or not jd.strip():
        return None, []
    jd_skills, cv_skills = extract_skills(jd), extract_skills(cv)
    missing = sorted(jd_skills - cv_skills)
    tfidf = TfidfVectorizer(stop_words="english").fit_transform([cv, jd])
    sim = min(1.0, float(cosine_similarity(tfidf[0], tfidf[1])[0][0]) * 2)
    if jd_skills:
        score = 0.7 * len(jd_skills & cv_skills) / len(jd_skills) + 0.3 * sim
    else:
        score = sim
    return round(score * 100), missing
