# Chess Arcade Web Update

Updated browser version with:
- email + password accounts
- player name and birth date at registration
- persistent coins, wins, losses, draws and unlocked boards
- login/logout
- Play Offline
- Play With Computer
- Play Online with random matchmaking
- colour selection
- captured pieces side panel
- square responsive board
- board store
- server-side legal-move validation for online games

## Local

```bash
pip install -r requirements.txt
python -m uvicorn app:app --reload --port 8000
```
Open http://127.0.0.1:8000

## Render

The included render.yaml creates a free web service and a free Render Postgres database. Render currently says free Postgres databases expire after 30 days, so this is suitable for testing, not permanent production player data. Upgrade the database or use another permanent database before collecting real players' information.

Repository structure must be:

```text
app.py
requirements.txt
render.yaml
.python-version
README.md
static/
  index.html
  app.js
  style.css
```
