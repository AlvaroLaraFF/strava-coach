---
name: strava-setup
description: >
  Step-by-step setup wizard for strava-coach. Checks prerequisites, installs
  dependencies, guides through Strava app registration and OAuth authorization.
  Run this once before using /strava-coach.
allowed-tools: Bash(python3 *), Bash(pip *), Bash(pip3 *), Bash(echo *), Bash(cat *), Read
---

# /strava-setup

Full setup wizard for the strava-coach project. Guides the user from zero to a working Strava integration.

**IMPORTANT:** Run each step sequentially. Do NOT skip steps. Wait for user confirmation before proceeding to the next step.

---

## Step 1: Check Python

```bash
python3 --version
```

- If Python 3.10+ is available, proceed.
- If not, tell the user to install Python 3.10 or higher and stop.

---

## Step 2: Check and install dependencies

```bash
python3 -c "import requests; print('requests', requests.__version__)" 2>&1
```

- If `requests` is installed, show the version and proceed.
- If it fails, ask the user: "The `requests` library is not installed. Install it now with pip?"
  - If yes:
    ```bash
    pip3 install requests
    ```
  - If no, stop and tell them to install it manually.

---

## Step 3: Initialize the database (only if missing)

First check whether the database file exists and already has the expected tables:

```bash
python3 -c "
import os, sqlite3, sys
sys.path.insert(0, '.')
from strava.client import get_default_db_path
db = get_default_db_path()
required = {'oauth_tokens', 'activities', 'athlete_stats'}
if not os.path.isfile(db):
    print('DB_MISSING', db)
else:
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()
        existing = {r[0] for r in rows}
    finally:
        conn.close()
    missing = required - existing
    if missing:
        print('DB_INCOMPLETE', db, 'missing=' + ','.join(sorted(missing)))
    else:
        print('DB_OK', db)
"
```

- If the output starts with `DB_OK`, the database is already initialized — show the path and proceed to Step 4 WITHOUT running `init_db`.
- If the output starts with `DB_MISSING` or `DB_INCOMPLETE`, run the initializer:

  ```bash
  python3 -c "
  import sys; sys.path.insert(0, '.')
  from strava.db import init_db
  from strava.client import get_default_db_path
  db = get_default_db_path()
  init_db(db)
  print('Database initialized at:', db)
  "
  ```

  If it succeeds, proceed. If it fails, show the error and stop.

---

## Step 4: Check tokens and credentials

**First**, check if there are already valid tokens in the database:

```bash
python3 -c "
import sys, time
sys.path.insert(0, '.')
from strava.db import load_token
from strava.client import get_default_db_path
token = load_token(get_default_db_path())
if token:
    expired = 'EXPIRED' if token['expires_at'] < time.time() else 'valid'
    print(f'TOKEN_FOUND athlete={token[\"athlete_id\"]} status={expired}')
else:
    print('NO_TOKEN')
"
```

### If a valid token exists:

Skip directly to Step 6 (Verify connection) without asking. Only ask the user when there is an actual blocker. Mention briefly that an existing valid token was found and is being reused.

### If NO token or token is EXPIRED:

The user needs credentials in the `.env` file. Check if `.env` exists and has values:

```bash
python3 -c "
import os
env_path = '.env'
if not os.path.isfile(env_path):
    print('NO_ENV_FILE')
else:
    cid, secret = '', ''
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line.startswith('STRAVA_CLIENT_ID='):
                cid = line.split('=', 1)[1].strip()
            elif line.startswith('STRAVA_CLIENT_SECRET='):
                secret = line.split('=', 1)[1].strip()
    placeholders = ('your_client_id_here', 'your_client_secret_here', '')
    if cid in placeholders or secret in placeholders:
        print('ENV_INCOMPLETE')
    else:
        print('ENV_OK')
"
```

#### If `NO_ENV_FILE` or `ENV_INCOMPLETE`:

Tell the user:

> **You need to configure your Strava credentials.** Follow these steps:
>
> 1. Go to **https://www.strava.com/settings/api** and create an app (if you don't have one yet):
>    - **Application Name**: anything you like (e.g. "My Coach")
>    - **Category**: any
>    - **Club**: leave empty
>    - **Website**: `http://localhost`
>    - **Authorization Callback Domain**: `localhost`
> 2. Copy the **Client ID** and **Client Secret** shown by Strava.
> 3. In the project root there is a `.env.example` file. Copy it to `.env`:
>    ```
>    cp .env.example .env
>    ```
> 4. Edit `.env` and paste your real Client ID and Client Secret values.
>
> **IMPORTANT:** The `.env` file is in `.gitignore` and must NEVER be committed. It contains your private credentials.

Then STOP and wait for the user to confirm they have filled in the `.env` file.

After confirmation, re-run the `.env` check above to verify it reads `ENV_OK`. Do NOT proceed until verified.

#### If `ENV_OK`:

Proceed to Step 5.

---

## Step 5: OAuth authorization

Run the OAuth setup:

```bash
python3 .claude/skills/strava-setup/scripts/setup_oauth.py
```

Tell the user:
> **A URL will open. Open it in your browser, authorize the app on Strava and come back here.**
> The script will capture the authorization automatically.

Wait for the script to complete. If it outputs `"success": true`, show the athlete name and proceed. If it fails, show the error and help troubleshoot.

---

## Step 6: Verify connection

Test that the API works end-to-end. **Use `--dry-run`** so that the
verification does NOT persist activities to the DB — persistence is the job
of the full-history sync in Step 7.

```bash
python3 .claude/skills/strava-coach/scripts/list_activities.py --dry-run --limit 3
```

- If `"success": true`, show the 3 activities in a formatted table and congratulate the user.
- If it fails, show the error and help troubleshoot.

---

## Step 7: Full-history sync

**This is critical.** Before any analytics can work reliably, the DB needs
the complete activity history. Run a full summary sync (not incremental):

```bash
python3 .claude/skills/strava-sync/scripts/sync.py --level summary --full
```

Show the user the total count of activities synced and the date range.

Then upgrade all activities to detailed payloads (best_efforts, splits):

> **Aviso al usuario:** La descarga de detalles hace una llamada a la API por cada actividad, con pausas para respetar el rate limit de Strava. Con muchas actividades esto puede tardar **varios minutos** (aprox. 5 min por cada 100 actividades). Es normal — no es un error.

```bash
python3 .claude/skills/strava-sync/scripts/sync.py --level details
```

Show the count of activities upgraded. If any failed, note it but proceed.

---

## Step 8: User profile (optional)

Ask the user for basic profile data. **All fields are optional** — the user can skip any or all of them. Explain that having this data improves the accuracy of training analytics (e.g., W/kg calculations need weight, TRIMP uses gender-specific coefficients).

Fields to ask for:
- **Name** — display name
- **Birth date** — YYYY-MM-DD (critical for age-based physiological formulas: HR max, VO2max classification, HR rest defaults)
- **Height** — in cm
- **Weight** — in kg
- **Gender** — M or F (used for Tanaka vs Gulati HR max formula and TRIMP coefficients)

If the user provides at least one field, save the profile:

```bash
python3 .claude/skills/strava-setup/scripts/save_profile.py --name "<name>" --birth-date <YYYY-MM-DD> --height <cm> --weight <kg> --gender <M|F>
```

Only include flags for fields the user actually provided. If the user skips everything, proceed without saving.

If the user already has a profile (e.g., re-running setup), show the current values and ask if they want to update anything:

```bash
python3 -c "
import sys, json
sys.path.insert(0, '.')
from strava.db import load_user_profile
from strava.client import get_default_db_path
p = load_user_profile(get_default_db_path())
print(json.dumps(p) if p else 'NO_PROFILE')
"
```

---

## Step 9: Summary

Present a final checklist:

```
Setup complete!

  [x] Python 3 .............. installed
  [x] requests .............. installed
  [x] Database .............. initialized
  [x] .env .................. configured
  [x] OAuth token ........... authorized
  [x] Connection ............ verified
  [x] Full history sync ..... N activities (date_range)
  [x] Profile ............... saved (or: skipped)

You can now ask about your training — fitness, race predictions, pace zones, and more.
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `requests` not found after install | Try `python3 -m pip install requests` |
| OAuth callback not received | Make sure port 8080 is free. Try `--port 9090` |
| Token refresh fails | Re-run `/strava-setup` to get a new token |
| `.env` not found | Copy `.env.example` to `.env` and fill in your credentials |
| Credentials not loading | Make sure `.env` has no spaces around `=` and no quotes around values |
