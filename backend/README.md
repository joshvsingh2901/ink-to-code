# InkToCode backend

Minimal FastAPI foundation for local frontend-to-backend communication.

## Run the backend

From the repository root:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The local frontend origin defaults to `http://localhost:3000`. To use another origin:

```bash
FRONTEND_ORIGIN=http://localhost:3001 uvicorn app.main:app --reload --port 8000
```

Available endpoints:

- Health: [http://localhost:8000/health](http://localhost:8000/health)
- API documentation: [http://localhost:8000/docs](http://localhost:8000/docs)

## Run the frontend

In a second terminal, from the repository root:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). During development, the interface shows whether the backend health endpoint is available.
