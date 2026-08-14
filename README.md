# Deepgram Transcriber

A small transcription tool with two parts:

- **`server/`** — a FastAPI backend that accepts an audio/video upload, extracts audio with `ffmpeg` if needed, sends it to Deepgram for diarized transcription, and stores job status/results in SQLite.
- **`client/`** — a Tkinter desktop app (can be packaged into a standalone `.exe`/binary) that lets a user upload a file to the server, poll job status, and view results.

## How it works

1. Client uploads a file to `POST /upload` on the server.
2. Server saves it, kicks off a background job, and immediately returns a `job_id`.
3. If the file is a video (`.mp4`, `.mov`, `.avi`, `.mkv`, `.webm`, `.m4v`, `.flv`, `.wmv`), `ffmpeg` extracts a 16kHz mono WAV first.
4. The audio is sent to Deepgram (`nova-2`, diarization + smart formatting enabled).
5. Client polls `GET /job/{job_id}` every few seconds until `status` is `completed` or `failed`.

## Prerequisites

- Python 3.11+
- [`ffmpeg`](https://ffmpeg.org/download.html) installed and on your `PATH` (only needed if you run the server outside Docker)
- A [Deepgram API key](https://console.deepgram.com/)

## 1. Run the server locally

```bash
cd server
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Provide your API key
export DEEPGRAM_API_KEY=your_key_here   # Windows: set DEEPGRAM_API_KEY=your_key_here

python main.py
# or: uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

The server listens on `http://localhost:8000`.

### API endpoints

| Method | Path              | Description                                   |
|--------|--------------------|-----------------------------------------------|
| POST   | `/upload`          | Upload a file (`multipart/form-data`, field `file`). Returns `{job_id, status}`. |
| GET    | `/job/{job_id}`    | Get status/result for a single job.           |
| GET    | `/jobs?limit=20`   | List recent jobs.                              |

## 2. Run the server with Docker

```bash
cd server
echo "DEEPGRAM_API_KEY=your_key_here" > .env
cd ..
docker compose up --build
```

This builds the image (installs `ffmpeg` inside the container) and serves the API on `http://localhost:8000`. `docker-compose.yml` reads `server/.env` for the API key — this file is git-ignored, so create it yourself and never commit it.

## 3. Deploy the server to Render

`render.yaml` is already set up for a Docker web service on Render:

1. Push this repo to GitHub/GitLab.
2. In Render, create a new **Blueprint** from the repo (it will pick up `render.yaml`).
3. When prompted, set the `DEEPGRAM_API_KEY` environment variable (it's marked `sync: false`, so Render won't store it in the blueprint — you enter it in the dashboard).
4. Deploy. Note the public URL Render gives you (e.g. `https://your-app.onrender.com`).

> **Note:** the free Render plan spins the service down when idle (first request after idling will be slow) and uses an ephemeral filesystem, so `jobs.db` and all job history are wiped on every restart/redeploy. For anything long-lived, point the app at a persistent database instead of SQLite.

## 4. Run the desktop client

```bash
cd client
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

Edit `client/config.json` and set `server_url` to wherever your server is running:

```json
{
    "server_url": "http://127.0.0.1:8000"
}
```

(or your Render URL, e.g. `https://your-app.onrender.com`). Then run:

```bash
python client.py
```

Use **Browse** to pick an audio/video file, **Upload & Transcribe** to send it, and double-click a row in **Recent Jobs** to view its transcript once it's done.

## 5. Build the client into a standalone executable

```bash
cd client
python build.py
```

This uses PyInstaller to produce a single-file, windowed executable named `Transcriber` (`Transcriber.exe` on Windows) in `client/dist/`, bundling `config.json` alongside it. Ship this executable to end users — they don't need Python installed.

> Ignore/delete `Transcriber.spec` — it contains a hardcoded path from the original developer's machine and won't work on another computer. `build.py` regenerates a correct spec automatically. Also note `build.py`'s `--add-data` argument uses the Windows path separator (`;`); if you build on macOS/Linux, change it to `config.json:.`.

## Known issues / before going to production

- **Blocking work in an async endpoint:** the server's background job runs `ffmpeg` and calls Deepgram synchronously inside an `async def`, which blocks the whole server for the duration of each job. Fine for occasional personal use; under real concurrent traffic, move this to a thread pool (`asyncio.to_thread`) or a proper task queue.
- **`tempfile.mktemp()`** is used for the extracted-audio path in `extract_audio()`; it's deprecated due to a file-creation race condition. Prefer `tempfile.NamedTemporaryFile(delete=False)`.
- **Unpinned Deepgram SDK version** (`deepgram-sdk>=3.0.0`). The code uses the v4.x API shape; pin a version range (e.g. `>=4.0.0,<5`) so a future SDK release can't silently break transcription.
- **SQLite is single-instance only** — don't scale the server to multiple workers/replicas without swapping to a real database (Postgres, etc.), and remember Render's free-tier disk is ephemeral.
- **No auth or upload size limit** on `/upload` — anyone with the URL can use your Deepgram quota. Add an API key check or rate limiting before exposing this publicly.

## Project structure

```
.
├── client/
│   ├── client.py          # Tkinter desktop app
│   ├── config.json        # Points the client at a server URL
│   ├── build.py           # Builds a standalone executable via PyInstaller
│   └── requirements.txt
├── server/
│   ├── main.py             # FastAPI app
│   ├── Dockerfile
│   └── requirements.txt
├── docker-compose.yml
├── render.yaml
└── Transcriber.spec        # Auto-generated by build.py; safe to delete/regenerate
```
