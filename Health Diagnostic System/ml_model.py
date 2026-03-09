"""
ml_model.py — Ensemble ML model (Random Forest + Naive Bayes + SVM)
All symptom strings are stripped of whitespace at load time so they
match the chatbot engine and form submissions consistently.
"""

import pandas as pd
from sklearn.preprocessing import MultiLabelBinarizer
from sklearn.ensemble import RandomForestClassifier, VotingClassifier
from sklearn.naive_bayes import BernoulliNB
from sklearn.svm import SVC

data = pd.read_csv("dataset/dataset.csv")
symptom_cols = data.columns[1:]

# Strip whitespace from every symptom value — the raw CSV has leading spaces
symptoms_list = []
for _, row in data.iterrows():
    symptoms_list.append([s.strip() for s in row[symptom_cols].dropna()])

mlb = MultiLabelBinarizer()
X   = mlb.fit_transform(symptoms_list)
y   = data["Disease"].str.strip()

# Ensemble: RF + Naive Bayes + SVM (soft voting)
rf  = RandomForestClassifier(n_estimators=100, random_state=42)
nb  = BernoulliNB()
svm = SVC(kernel="linear", probability=True, random_state=42)

model = VotingClassifier(
    estimators=[("rf", rf), ("nb", nb), ("svm", svm)],
    voting="soft"
)
model.fit(X, y)

# symptom_columns is used by the UI checkbox grid — now clean, no leading spaces
symptom_columns = mlb.classes_


def predict_disease(symptoms):
    """Predict top 5 diseases for a list of symptom keys (stripped)."""
    # Strip inputs defensively
    symptoms = [s.strip() for s in symptoms]
    known = [s for s in symptoms if s in mlb.classes_]
    if not known:
        known = symptoms  # fallback — let MLB handle unknowns
    vec   = mlb.transform([known])
    probs = model.predict_proba(vec)[0]
    results = sorted(zip(model.classes_, probs), key=lambda x: x[1], reverse=True)
    return results[:5]


def get_confidence(predictions):
    """Return top prediction confidence as a percentage float."""
    if not predictions:
        return 0
    return round(float(predictions[0][1]) * 100, 1)