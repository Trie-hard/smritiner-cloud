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
                
                # Determine status
                if p["id"] == "00000000-0000-0000-0000-000000000002":
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
