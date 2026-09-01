import os
import aiosqlite
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

logger = logging.getLogger("smritiner.db")
DB_PATH = os.environ.get("DB_PATH", "smritiner.db")

async def get_db():
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL;")
    return db

async def init_db():
    db = await get_db()
    try:
        # Create Tables
        await db.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            id TEXT PRIMARY KEY,
            full_name TEXT NOT NULL,
            age INTEGER NOT NULL,
            primary_language TEXT NOT NULL,
            baseline_theta REAL NOT NULL,
            caregiver_phone TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS caregivers (
            id TEXT PRIMARY KEY,
            patient_id TEXT,
            phone_number TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            game_type TEXT NOT NULL,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            items_attempted INTEGER NOT NULL,
            items_correct INTEGER NOT NULL,
            final_theta REAL,
            sem REAL
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS patient_telemetry_events (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            patient_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_data TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS daily_theta_rollup (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id TEXT NOT NULL,
            bucket TEXT NOT NULL,
            mean_theta REAL NOT NULL,
            min_theta REAL NOT NULL,
            max_theta REAL NOT NULL,
            session_count INTEGER NOT NULL,
            total_events INTEGER NOT NULL,
            UNIQUE(patient_id, bucket)
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS caregiver_mutations (
            id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            caregiver_id TEXT,
            mutation_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            lamport_clock INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        """)

        await db.execute("""
        CREATE TABLE IF NOT EXISTS clinical_alerts (
            id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            patient_name TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL
        );
        """)

        await db.commit()
        await seed_demo_data(db)
        logger.info("Database schema initialized and verified.")
    finally:
        await db.close()

async def seed_demo_data(db: aiosqlite.Connection):
    # Check if patients already exist
    async with db.execute("SELECT COUNT(*) as cnt FROM patients") as cursor:
        row = await cursor.fetchone()
        if row and row["cnt"] > 0:
            return

    logger.info("Seeding initial demo personas and 30-day clinical trajectories...")

    now = datetime.now(timezone.utc)
    hashed_pw = "$2b$12$.eEJOAr04q/RjszObh4XEeDwLl4y70asqxEKMr7XDNTbJ.822wQk6"

    # Patients
    personas = [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "name": "Biren Da",
            "age": 74,
            "lang": "as",
            "theta_start": 0.3,
            "theta_end": 0.27,
            "status": "STABLE",
            "phone": "+919876543210"
        },
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "name": "Kong Mary",
            "age": 78,
            "lang": "bn",
            "theta_start": -0.8,
            "theta_end": -1.49,
            "status": "DECLINING",
            "phone": "+919876543211"
        },
        {
            "id": "00000000-0000-0000-0000-000000000003",
            "name": "Subedar Thapa",
            "age": 72,
            "lang": "ne",
            "theta_start": 1.2,
            "theta_end": 1.23,
            "status": "STABLE",
            "phone": "+919876543212"
        }
    ]

    for p in personas:
        await db.execute("""
            INSERT OR REPLACE INTO patients (id, full_name, age, primary_language, baseline_theta, caregiver_phone, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (p["id"], p["name"], p["age"], p["lang"], p["theta_start"], p["phone"], now.isoformat(), now.isoformat()))

    # Caregivers
    caregiver_records = [
        ("00000000-0000-0000-0000-000000000101", "00000000-0000-0000-0000-000000000001", "+919876543210", hashed_pw, "PRIMARY", now.isoformat()),
        ("00000000-0000-0000-0000-000000000102", "00000000-0000-0000-0000-000000000001", "9876543210", hashed_pw, "PRIMARY", now.isoformat())
    ]
    for c in caregiver_records:
        await db.execute("""
            INSERT OR REPLACE INTO caregivers (id, patient_id, phone_number, password_hash, role, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, c)

    # 30-Day Daily Trajectories
    game_types = ["reaction_time", "memory_grid", "symbol_match", "word_recall"]
    
    for p in personas:
        t_start = p["theta_start"]
        t_end = p["theta_end"]
        
        for d in range(30):
            day_dt = now - timedelta(days=(29 - d))
            day_str = day_dt.strftime("%Y-%m-%d")
            
            # Linear trend with slight gaussian noise
            frac = d / 29.0
            theta_val = round(t_start + (t_end - t_start) * frac + ((d % 3) - 1) * 0.03, 3)
            
            # Daily rollup
            await db.execute("""
                INSERT OR REPLACE INTO daily_theta_rollup (patient_id, bucket, mean_theta, min_theta, max_theta, session_count, total_events)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (p["id"], day_str, theta_val, round(theta_val - 0.05, 3), round(theta_val + 0.05, 3), 2, 18))

            # Game Sessions
            sess_id = f"sess_{p['id'][:8]}_{d}"
            await db.execute("""
                INSERT OR REPLACE INTO sessions (session_id, patient_id, game_type, started_at, completed_at, items_attempted, items_correct, final_theta, sem)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sess_id, p["id"], game_types[d % len(game_types)],
                day_dt.isoformat(), (day_dt + timedelta(minutes=6)).isoformat(),
                10, 8 if theta_val > 0 else 5, theta_val, 0.28
            ))

    # Alerts
    await db.execute("""
        INSERT OR REPLACE INTO clinical_alerts (id, patient_id, patient_name, alert_type, severity, message, details, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "alert-kong-01",
        "00000000-0000-0000-0000-000000000002",
        "Kong Mary",
        "RAPID_THETA_DECLINE",
        "HIGH",
        "Cognitive ability (θ) dropped by 0.69 over 30 days (crossed -1.2 threshold).",
        json.dumps({"baseline": -0.8, "current": -1.49, "delta": -0.69, "recommendation": "Conduct MoCA evaluation"}),
        now.isoformat()
    ))

    await db.commit()
    logger.info("Demo personas and 30-day trajectories successfully seeded!")

# Query Helpers
async def authenticate_caregiver(phone_number: str) -> Optional[Dict[str, Any]]:
    db = await get_db()
    try:
        clean_phone = phone_number.strip()
        async with db.execute("SELECT * FROM caregivers WHERE phone_number = ?", (clean_phone,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
        # Try with or without +91
        alt_phone = clean_phone[3:] if clean_phone.startswith("+91") else f"+91{clean_phone}"
        async with db.execute("SELECT * FROM caregivers WHERE phone_number = ?", (alt_phone,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)
        return None
    finally:
        await db.close()

async def get_all_patients() -> List[Dict[str, Any]]:
    db = await get_db()
    try:
        async with db.execute("SELECT * FROM patients") as cursor:
            rows = await cursor.fetchall()
            results = []
            for r in rows:
                p = dict(r)
                # Get last session time and session count
                async with db.execute("SELECT COUNT(*) as sc, MAX(started_at) as lst FROM sessions WHERE patient_id = ?", (p["id"],)) as cur2:
                    s_row = await cur2.fetchone()
                    p["session_count"] = s_row["sc"] if s_row else 30
                    p["last_session_time"] = s_row["lst"] if s_row and s_row["lst"] else p["created_at"]
                
                # Determine status from theta trajectory when available
                async with db.execute(
                    "SELECT mean_theta FROM daily_theta_rollup WHERE patient_id = ? ORDER BY bucket ASC LIMIT 1",
                    (p["id"],),
                ) as cur_first:
                    first = await cur_first.fetchone()
                async with db.execute(
                    "SELECT mean_theta FROM daily_theta_rollup WHERE patient_id = ? ORDER BY bucket DESC LIMIT 1",
                    (p["id"],),
                ) as cur_last:
                    last = await cur_last.fetchone()

                if first and last:
                    delta = float(last["mean_theta"]) - float(first["mean_theta"])
                    if delta <= -0.5:
                        p["status"] = "DECLINING"
                    elif delta <= -0.2:
                        p["status"] = "ATTENTION"
                    else:
                        p["status"] = "STABLE"
                elif p["id"] == "00000000-0000-0000-0000-000000000002":
                    p["status"] = "DECLINING"
                else:
                    p["status"] = "STABLE"
                results.append(p)
            return results
    finally:
        await db.close()

async def get_patient_trend(patient_id: str, days: int = 30) -> List[Dict[str, Any]]:
    db = await get_db()
    try:
        async with db.execute(
            "SELECT bucket as date, mean_theta as theta, min_theta as theta_ci_lower, max_theta as theta_ci_upper, session_count FROM daily_theta_rollup WHERE patient_id = ? ORDER BY bucket ASC LIMIT ?",
            (patient_id, days)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
    finally:
        await db.close()

async def get_patient_sessions(patient_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    db = await get_db()
    try:
        async with db.execute(
            "SELECT session_id, game_type, started_at, completed_at, items_attempted, items_correct, final_theta, sem FROM sessions WHERE patient_id = ? ORDER BY started_at DESC LIMIT ?",
            (patient_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
    finally:
        await db.close()

async def get_alerts() -> List[Dict[str, Any]]:
    db = await get_db()
    try:
        async with db.execute("SELECT * FROM clinical_alerts ORDER BY created_at DESC") as cursor:
            rows = await cursor.fetchall()
            return [dict(r) for r in rows]
    finally:
        await db.close()


async def upsert_patient(conn: aiosqlite.Connection, patient: Dict[str, Any]) -> None:
    """Insert or update a patient row from a mobile push payload."""
    now = datetime.now(timezone.utc).isoformat()
    patient_id = patient.get("id")
    if not patient_id:
        return

    async with conn.execute("SELECT id FROM patients WHERE id = ?", (patient_id,)) as cursor:
        exists = await cursor.fetchone()

    full_name = patient.get("full_name") or patient.get("name") or "Unknown"
    age = int(patient.get("age") or 0)
    lang = patient.get("primary_language") or "en"
    theta = float(patient.get("baseline_theta") if patient.get("baseline_theta") is not None else 0.0)
    phone = patient.get("caregiver_phone")

    if exists:
        await conn.execute("""
            UPDATE patients
            SET full_name = ?, age = ?, primary_language = ?,
                baseline_theta = COALESCE(?, baseline_theta),
                caregiver_phone = COALESCE(?, caregiver_phone),
                updated_at = ?
            WHERE id = ?
        """, (full_name, age, lang, theta, phone, now, patient_id))
    else:
        await conn.execute("""
            INSERT INTO patients (
                id, full_name, age, primary_language, baseline_theta,
                caregiver_phone, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (patient_id, full_name, age, lang, theta, phone, now, now))


async def get_patient_theta(conn: aiosqlite.Connection, patient_id: str) -> Optional[float]:
    async with conn.execute(
        "SELECT baseline_theta FROM patients WHERE id = ?", (patient_id,)
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        return None
    return float(row["baseline_theta"])


async def update_patient_theta(
    conn: aiosqlite.Connection,
    patient_id: str,
    theta: float,
    updated_at: str,
) -> None:
    await conn.execute(
        "UPDATE patients SET baseline_theta = ?, updated_at = ? WHERE id = ?",
        (theta, updated_at, patient_id),
    )


async def upsert_daily_theta_rollup(
    conn: aiosqlite.Connection,
    patient_id: str,
    started_at: str,
    theta: float,
) -> None:
    """Merge a session into the daily theta rollup bucket for trend charts."""
    try:
        day = started_at[:10]
        if "T" not in started_at and len(started_at) < 10:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    async with conn.execute(
        "SELECT mean_theta, min_theta, max_theta, session_count, total_events "
        "FROM daily_theta_rollup WHERE patient_id = ? AND bucket = ?",
        (patient_id, day),
    ) as cursor:
        row = await cursor.fetchone()

    if row:
        prev_count = int(row["session_count"] or 0)
        new_count = prev_count + 1
        prev_mean = float(row["mean_theta"] or theta)
        new_mean = round(((prev_mean * prev_count) + theta) / new_count, 3)
        new_min = round(min(float(row["min_theta"] or theta), theta), 3)
        new_max = round(max(float(row["max_theta"] or theta), theta), 3)
        new_events = int(row["total_events"] or 0) + 1
        await conn.execute("""
            UPDATE daily_theta_rollup
            SET mean_theta = ?, min_theta = ?, max_theta = ?,
                session_count = ?, total_events = ?
            WHERE patient_id = ? AND bucket = ?
        """, (new_mean, new_min, new_max, new_count, new_events, patient_id, day))
    else:
        await conn.execute("""
            INSERT INTO daily_theta_rollup (
                patient_id, bucket, mean_theta, min_theta, max_theta,
                session_count, total_events
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (patient_id, day, round(theta, 3), round(theta, 3), round(theta, 3), 1, 1))


async def maybe_create_decline_alert(
    conn: aiosqlite.Connection,
    patient_id: str,
    new_theta: float,
    created_at: str,
    prior_baseline: Optional[float] = None,
) -> Optional[Dict[str, Any]]:
    """Create a HIGH alert when theta drops ≥ 0.5 from the prior baseline."""
    async with conn.execute(
        "SELECT full_name, baseline_theta FROM patients WHERE id = ?",
        (patient_id,),
    ) as cursor:
        patient = await cursor.fetchone()
    if not patient:
        return None

    if prior_baseline is not None:
        baseline = float(prior_baseline)
    else:
        async with conn.execute(
            "SELECT mean_theta FROM daily_theta_rollup WHERE patient_id = ? "
            "ORDER BY bucket ASC LIMIT 1",
            (patient_id,),
        ) as cursor:
            first = await cursor.fetchone()
        baseline = float(first["mean_theta"]) if first else float(patient["baseline_theta"] or 0.0)

    delta = new_theta - baseline
    if delta > -0.5:
        return None

    alert_id = f"alert-{patient_id[:8]}-{int(datetime.now().timestamp())}"
    message = (
        f"Cognitive ability (θ) dropped by {abs(delta):.2f} "
        f"(baseline {baseline:.2f} → {new_theta:.2f})."
    )
    details = json.dumps({
        "baseline": baseline,
        "current": new_theta,
        "delta": round(delta, 3),
        "recommendation": "Conduct MoCA / HMSE evaluation",
    })
    await conn.execute("""
        INSERT OR REPLACE INTO clinical_alerts (
            id, patient_id, patient_name, alert_type, severity, message, details, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        alert_id, patient_id, patient["full_name"],
        "RAPID_THETA_DECLINE", "HIGH", message, details, created_at,
    ))
    return {
        "id": alert_id,
        "patientId": patient_id,
        "patient_name": patient["full_name"],
        "message": message,
        "severity": "high",
        "timestamp": created_at,
    }
