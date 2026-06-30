# Postmortem — Streamlit Cloud "Oh no. Error running app."

## Symptom
The hosted app (carrier-tender-optimization…streamlit.app) showed a bare
**"Oh no. Error running app."** page on every visit. It rendered perfectly when
run locally.

## Root cause (confirmed)
**A dependency could not be installed on Streamlit Cloud's Python runtime, so the
app failed to boot — it was never an application-code bug.**

- Streamlit Community Cloud now provisions **Python 3.13** (the deploy logs show a
  `/home/adminuser/venv/lib/python3.13/…` path).
- `requirements.txt` pinned **`numpy==1.26.4`**, which has **no cp313 (Python 3.13)
  wheel** — NumPy only started shipping 3.13 wheels at 2.1.0.
- With no wheel, `uv`/pip fell back to **building NumPy 1.26.4 from source** on the
  hosted image. That build failed, the dependency set was broken, and Streamlit
  could not start the script → the generic **"Oh no"** page (shown *before* any of
  our code runs, which is why it looked identical at every commit).

## Why it was hard to find
- **It worked locally** because this dev machine resolved **numpy 2.x / pandas 2.x**,
  not the pinned 1.26.4 — so the broken pin never surfaced locally.
- The error page is **pre-script**: a boot/install failure shows the same "Oh no"
  as a code crash, so `try/except` in `streamlit_app.py`, `showErrorDetails="full"`,
  and the Arrow render guard all had no effect (the script never started).
- `/healthz` returned **200** the whole time (the Streamlit *server* was up; only
  the *app script* couldn't start), which misleadingly suggested a healthy app.
- Private-app **viewer auth** made `curl`/WebFetch only see a login redirect; they
  could not render the JS app to reveal the "Oh no" screen.

## What actually found it
A **bisection** (per the user's suggestion): reverting to the pre-today baseline
`d167ec4` and seeing it **still fail on Cloud** proved the application code was
innocent and pointed the investigation at the deploy environment, where the
numpy/Python-3.13 wheel gap was identified.

## The fix
`requirements.txt` — relaxed the hard pins to floors that ship prebuilt **cp313**
wheels and are mutually compatible:

```
streamlit>=1.44.0
pandas>=2.2.3
numpy>=2.1.0          # was numpy==1.26.4  ← the boot-breaking pin
openpyxl>=3.1.5
python-docx>=1.2.0
pulp>=2.9.0
scikit-learn>=1.5.2
plotly>=5.24.1
boto3>=1.34.0
python-dotenv>=1.0.0
```

Also reduced the repo-root `pyproject.toml` to **pytest config only** (removed its
`[build-system]`/`[project]`/`[tool.setuptools]`), so Cloud's installer no longer
treats the repo as an installable project and uses `requirements.txt`
unambiguously. (Secondary hardening; the numpy pin was the actual blocker.)

Result: the dashboard boots and renders on Cloud (verified via headless-browser
screenshot).

## Diagnostic tooling added
`scripts/check_deployment.py` — drives headless Chromium (Playwright), screenshots
the live app, reads visible text + console/network errors, and classifies the
state RUNNING / ERROR / LOGIN / SLEEPING. This is what surfaced the real "Oh no"
screen that `curl`/WebFetch could not.

## Guardrails to avoid a repeat
- Pin dependency **floors** (or test against the exact Python version Cloud uses);
  don't hard-pin a version that lacks a wheel for the runtime's Python.
- When the app "works locally but not on Cloud," check the **deploy/build logs and
  the installed dependency/Python versions first** — a boot/install failure looks
  identical to a code crash on the "Oh no" page.
- A clean `/healthz` 200 does **not** mean the app script is running.
