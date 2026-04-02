```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```


```bash
ssh mia@mia.local
zellij attach spaceselflog

z spaceselflog

cd server

uv run python ingest_server.py
# cannot just `python ingest_server.py`
```


```bash
ssh -L 8000:127.0.0.1:8000 mia@mia.local
# then open http://localhost:8000 in browser
```