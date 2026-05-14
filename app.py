from flask import (Flask, request, jsonify, render_template,
                   Response, stream_with_context, make_response, session, redirect)
import json, os, time, queue, threading, zipfile, io
from datetime import datetime, timedelta
from database import (init_db, upsert_device, get_device, get_all_devices,
                      set_locked, set_all_locked, set_unlock_time,
                      ping_device, mark_offline, get_settings, save_settings,
                      add_log, get_logs, get_device_logs, now)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "hx_v3_secret_2025_maxmax")

# ── SSE CLIENTS ─────────────────────────────────────────
sse_clients   = {}   # device_id → [Queue, ...]
admin_clients = []   # admin dashboard SSE
sse_lock      = threading.Lock()

init_db()

# ── ADMIN CREDENTIALS ───────────────────────────────────
ADMIN_EMAIL    = "pankaj626252@gmail.com"
ADMIN_PASSWORD = "626252"

# ────────────────────────────────────────────────────────
#  HELPERS
# ────────────────────────────────────────────────────────
def push_device(device_id, data):
    """Push SSE event to a specific device."""
    with sse_lock:
        if device_id in sse_clients:
            dead = []
            for q in sse_clients[device_id]:
                try:    q.put_nowait(data)
                except: dead.append(q)
            for q in dead:
                try: sse_clients[device_id].remove(q)
                except: pass

def push_admin(data):
    """Push SSE event to all admin dashboard tabs."""
    with sse_lock:
        dead = []
        for q in admin_clients:
            try:    q.put_nowait(data)
            except: dead.append(q)
        for q in dead:
            try: admin_clients.remove(q)
            except: pass

def is_admin():
    return session.get("admin") == True

def device_to_dict(row):
    if row is None: return None
    return dict(row)

# ────────────────────────────────────────────────────────
#  AUTH
# ────────────────────────────────────────────────────────
@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        d = request.get_json(force=True) or {}
        if (d.get("email","").strip().lower() == ADMIN_EMAIL.lower() and
                d.get("password","") == ADMIN_PASSWORD):
            session["admin"] = True
            add_log("ADMIN", "LOGIN", request.remote_addr)
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": "Invalid credentials"})
    return render_template("admin.html")

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"ok": True})

# ────────────────────────────────────────────────────────
#  ADMIN PANEL
# ────────────────────────────────────────────────────────
@app.route("/")
def index():
    if not is_admin():
        return render_template("admin.html")
    return render_template("admin.html")

# ────────────────────────────────────────────────────────
#  DEVICE APIs  (called by Android app)
# ────────────────────────────────────────────────────────

@app.route("/api/register", methods=["POST"])
def api_register():
    try:
        d = request.get_json(force=True) or {}
        did = str(d.get("device_id","")).strip()
        if not did:
            return jsonify({"success": False, "error": "no id"})

        # Add remote IP as public IP if not provided
        if not d.get("public_ip"):
            d["public_ip"] = request.remote_addr or ""

        # Build name
        d["name"] = d.get("device_name") or d.get("model") or "Unknown"

        upsert_device(d)
        push_admin({"type": "device_update"})
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/status")
def api_status():
    try:
        did = request.args.get("id","").strip()
        dev = get_device(did)
        s   = get_settings()

        locked      = True
        unlock_time = None

        if dev:
            locked      = bool(dev["locked"])
            unlock_time = dev["unlock_time"]

            # Auto-unlock if scheduled time passed
            if unlock_time:
                try:
                    ut = datetime.strptime(unlock_time, "%Y-%m-%d %H:%M")
                    if datetime.now() >= ut:
                        set_locked(did, False)
                        push_device(did, {"locked": False})
                        push_admin({"type": "device_update"})
                        locked      = False
                        unlock_time = None
                except: pass

        return jsonify({
            "locked":       locked,
            "title":        s.get("title",    "Stay Focused!"),
            "subtitle":     s.get("subtitle", ""),
            "qr_url":       s.get("qr_url",   ""),
            "btn1_text":    s.get("btn1_text","UNLOCK"),
            "btn2_text":    s.get("btn2_text","Contact Admin"),
            "btn2_url":     s.get("btn2_url", ""),
            "unlock_time":  unlock_time
        })
    except Exception as e:
        return jsonify({"locked": True})


@app.route("/api/unlock")
def api_unlock():
    try:
        did = request.args.get("id","").strip()
        dev = get_device(did)
        if dev:
            return jsonify({"locked": bool(dev["locked"])})
        return jsonify({"locked": True})
    except:
        return jsonify({"locked": True})


@app.route("/api/ping", methods=["POST"])
def api_ping():
    try:
        d   = request.get_json(force=True) or {}
        did = str(d.get("device_id","")).strip()
        if did:
            ping_device(did, d)
            push_admin({"type": "ping", "device_id": did,
                        "battery": d.get("battery",""),
                        "online": True})
        return jsonify({"ok": True})
    except:
        return jsonify({"ok": False})


@app.route("/api/keepalive", methods=["GET","POST"])
def api_keepalive():
    """Prevents Render from sleeping. App pings this every 25s."""
    return jsonify({"ok": True, "ts": now()})


# ── DEVICE SSE ──────────────────────────────────────────
@app.route("/api/events")
def api_events():
    did = request.args.get("id","").strip()

    def generate():
        q = queue.Queue(maxsize=50)
        with sse_lock:
            if did not in sse_clients:
                sse_clients[did] = []
            sse_clients[did].append(q)
        try:
            # Send current state immediately
            dev = get_device(did)
            if dev:
                yield f"data: {json.dumps({'locked': bool(dev['locked'])})}\n\n"
            while True:
                try:
                    event = q.get(timeout=20)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield f"data: {json.dumps({'ping': True})}\n\n"
        except GeneratorExit:
            pass
        finally:
            with sse_lock:
                if did in sse_clients:
                    try: sse_clients[did].remove(q)
                    except: pass

    return Response(stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control":"no-cache",
                 "X-Accel-Buffering":"no",
                 "Connection":"keep-alive"})


# ────────────────────────────────────────────────────────
#  ADMIN APIs  (called by admin panel JS)
# ────────────────────────────────────────────────────────

@app.route("/admin/data")
def admin_data():
    if not is_admin(): return jsonify({"error":"unauthorized"}), 401
    devices = [device_to_dict(d) for d in get_all_devices()]
    s       = get_settings()
    total   = len(devices)
    online  = sum(1 for d in devices if d["online"])
    locked  = sum(1 for d in devices if d["locked"])
    return jsonify({
        "devices":  devices,
        "settings": s,
        "stats": {
            "total":    total,
            "online":   online,
            "offline":  total - online,
            "locked":   locked,
            "unlocked": total - locked
        }
    })


@app.route("/admin/device/<did>")
def admin_device(did):
    if not is_admin(): return jsonify({"error":"unauthorized"}), 401
    dev  = get_device(did)
    logs = get_device_logs(did, 50)
    return jsonify({
        "device": device_to_dict(dev),
        "logs":   [dict(l) for l in logs]
    })


@app.route("/admin/toggle", methods=["POST"])
def admin_toggle():
    if not is_admin(): return jsonify({"success":False,"error":"unauthorized"}), 401
    try:
        d      = request.get_json(force=True) or {}
        did    = str(d.get("device_id","")).strip()
        locked = bool(d.get("locked", True))
        dev    = get_device(did)
        if not dev:
            return jsonify({"success":False,"error":"device not found"})
        set_locked(did, locked)
        push_device(did, {"locked": locked})
        push_admin({"type":"device_update"})
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})


@app.route("/admin/bulk", methods=["POST"])
def admin_bulk():
    if not is_admin(): return jsonify({"success":False,"error":"unauthorized"}), 401
    try:
        d      = request.get_json(force=True) or {}
        locked = bool(d.get("locked", True))
        set_all_locked(locked)
        # Push to ALL connected devices
        devices = get_all_devices()
        for dev in devices:
            push_device(dev["device_id"], {"locked": locked})
        push_admin({"type":"device_update"})
        add_log("ADMIN", "BULK_" + ("LOCK" if locked else "UNLOCK"))
        return jsonify({"success":True, "count": len(devices)})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})


@app.route("/admin/schedule", methods=["POST"])
def admin_schedule():
    if not is_admin(): return jsonify({"success":False}), 401
    try:
        d   = request.get_json(force=True) or {}
        did = str(d.get("device_id","")).strip()
        ut  = d.get("unlock_time","").strip()
        dev = get_device(did)
        if not dev:
            return jsonify({"success":False,"error":"device not found"})
        set_unlock_time(did, ut)
        add_log(did, "SCHEDULE", ut)
        return jsonify({"success":True})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})


@app.route("/admin/settings", methods=["POST"])
def admin_settings():
    if not is_admin(): return jsonify({"success":False}), 401
    try:
        d = request.get_json(force=True) or {}
        allowed = ["title","subtitle","qr_url","btn1_text","btn2_text","btn2_url"]
        save_settings({k:d[k] for k in allowed if k in d})
        push_admin({"type":"settings_update"})
        return jsonify({"success":True})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})


@app.route("/admin/logs")
def admin_logs():
    if not is_admin(): return jsonify({"error":"unauthorized"}), 401
    logs = get_logs(300)
    return jsonify({"logs":[dict(l) for l in logs]})


@app.route("/admin/delete_device", methods=["POST"])
def admin_delete_device():
    if not is_admin(): return jsonify({"success":False}), 401
    try:
        from database import get_conn
        d   = request.get_json(force=True) or {}
        did = str(d.get("device_id","")).strip()
        get_conn().execute("DELETE FROM devices WHERE device_id=?", (did,))
        get_conn().commit()
        add_log(did, "DELETED")
        push_admin({"type":"device_update"})
        return jsonify({"success":True})
    except Exception as e:
        return jsonify({"success":False,"error":str(e)})


# ── ADMIN SSE (Live Dashboard) ──────────────────────────
@app.route("/admin/events")
def admin_events():
    if not is_admin():
        return Response("", status=401)

    def generate():
        q = queue.Queue(maxsize=100)
        with sse_lock:
            admin_clients.append(q)
        try:
            # Send initial data
            yield f"data: {json.dumps({'type':'connected'})}\n\n"
            while True:
                try:
                    event = q.get(timeout=20)
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield f"data: {json.dumps({'type':'ping'})}\n\n"
        except GeneratorExit:
            pass
        finally:
            with sse_lock:
                try: admin_clients.remove(q)
                except: pass

    return Response(stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control":"no-cache",
                 "X-Accel-Buffering":"no",
                 "Connection":"keep-alive"})


@app.route("/admin/download")
def admin_download():
    if not is_admin(): return "Unauthorized", 403
    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as zf:
            for f in ["app.py","database.py","requirements.txt",
                      "Procfile","hackrmax.db"]:
                if os.path.exists(f): zf.write(f)
            for root,dirs,files in os.walk("templates"):
                for file in files:
                    zf.write(os.path.join(root,file))
        buf.seek(0)
        return Response(buf.getvalue(),
            mimetype="application/zip",
            headers={"Content-Disposition":
                f"attachment; filename=hackrmax_backup_{int(time.time())}.zip"})
    except Exception as e:
        return str(e), 500


# ────────────────────────────────────────────────────────
#  BACKGROUND THREADS
# ────────────────────────────────────────────────────────

def offline_checker():
    """Mark devices offline if no ping in 90 seconds."""
    while True:
        time.sleep(30)
        try:
            mark_offline()
            push_admin({"type":"ping"})
        except: pass

def schedule_checker():
    """Check scheduled unlocks every 30 seconds."""
    while True:
        time.sleep(30)
        try:
            from database import get_conn
            conn = get_conn()
            rows = conn.execute(
                "SELECT device_id, unlock_time FROM devices "
                "WHERE unlock_time IS NOT NULL AND locked=1"
            ).fetchall()
            for row in rows:
                try:
                    ut = datetime.strptime(row["unlock_time"], "%Y-%m-%d %H:%M")
                    if datetime.now() >= ut:
                        set_locked(row["device_id"], False)
                        push_device(row["device_id"], {"locked": False})
                        push_admin({"type":"device_update"})
                except: pass
        except: pass

threading.Thread(target=offline_checker,  daemon=True).start()
threading.Thread(target=schedule_checker, daemon=True).start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)),
            threaded=True)
