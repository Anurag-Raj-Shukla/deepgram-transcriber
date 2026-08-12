import os
import uuid
import subprocess
import tempfile
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, File, UploadFile, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from deepgram import DeepgramClient
import sqlite3
import uvicorn

app = FastAPI(title="Deepgram Transcriber Server")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
db_path = "jobs.db"

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".flv", ".wmv"}

def init_db():
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY,
        filename TEXT,
        status TEXT DEFAULT 'pending',
        result TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        completed_at TIMESTAMP
    )''')
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def extract_audio(video_path: str) -> str:
    """Extract audio from video to 16kHz mono WAV (optimal for speech APIs)."""
    temp_audio = tempfile.mktemp(suffix=".wav")
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vn",                    # strip video
        "-acodec", "pcm_s16le",   # 16-bit PCM
        "-ar", "16000",           # 16 kHz
        "-ac", "1",               # mono
        "-threads", "2",          # limit CPU
        temp_audio
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return temp_audio

async def process_transcription(job_id: str, file_bytes: bytes, filename: str):
    conn = get_db()
    c = conn.cursor()
    tmp_path = None
    audio_path = None

    try:
        # Save uploaded bytes to temp file
        suffix = os.path.splitext(filename)[1].lower()
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        # If video, extract audio first
        if suffix in VIDEO_EXTS:
            c.execute("UPDATE jobs SET status=? WHERE id=?", ("extracting audio...", job_id))
            conn.commit()
            audio_path = extract_audio(tmp_path)
        else:
            audio_path = tmp_path

        # Read final audio bytes
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        c.execute("UPDATE jobs SET status=? WHERE id=?", ("transcribing...", job_id))
        conn.commit()

        deepgram = DeepgramClient(api_key=DEEPGRAM_API_KEY)

        response = deepgram.listen.v1.media.transcribe_file(
            request=audio_bytes,
            model="nova-2",
            smart_format=True,
            diarize=True,
            utterances=True,
            punctuate=True,
        )

        # Build diarized transcript
        utterances = response.results.utterances if response.results else []
        lines = []
        for u in utterances:
            speaker = getattr(u, "speaker", "?")
            text = getattr(u, "transcript", str(u))
            lines.append(f"Speaker {speaker}: {text}")

        result_text = "\n".join(lines) if lines else response.results.channels[0].alternatives[0].transcript

        c.execute(
            "UPDATE jobs SET status=?, result=?, completed_at=? WHERE id=?",
            ("completed", result_text, datetime.now().isoformat(), job_id)
        )
        conn.commit()

    except Exception as e:
        c.execute(
            "UPDATE jobs SET status=?, result=? WHERE id=?",
            ("failed", str(e), job_id)
        )
        conn.commit()
    finally:
        # Cleanup temp files
        for p in (audio_path, tmp_path):
            if p and os.path.exists(p):
                os.remove(p)
        conn.close()

@app.post("/upload")
async def upload_audio(background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    job_id = str(uuid.uuid4())
    audio_bytes = await file.read()

    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO jobs (id, filename, status) VALUES (?, ?, ?)",
        (job_id, file.filename, "processing")
    )
    conn.commit()
    conn.close()

    background_tasks.add_task(process_transcription, job_id, audio_bytes, file.filename)
    return {"job_id": job_id, "status": "processing"}

@app.get("/job/{job_id}")
async def get_job(job_id: str):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM jobs WHERE id=?", (job_id,))
    row = c.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    return dict(row)

@app.get("/jobs")
async def list_jobs(limit: int = 20):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "SELECT id, filename, status, created_at, completed_at FROM jobs ORDER BY created_at DESC LIMIT ?",
        (limit,)
    )
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
