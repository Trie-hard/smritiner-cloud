import os
import json
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple

from fastapi import FastAPI, HTTPException, Depends, Request, status
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database as db
import auth
from auth import TokenData, require_role, get_current_user
import irt_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("smritiner.cloud")

# ─────────────────────────────────────────────────────────────────────────────
# Lifespan
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing SmritiNER All-in-One Cloud Stack...")
    await db.init_db()
    logger.info("Database & Demo Personas ready.")
    yield
    logger.info("SmritiNER Cloud Stack stopped.")

app = FastAPI(
    title="SmritiNER Cloud — Unified Cognitive Health Platform",
    description="All-in-One Cloud Service: Caregiver Portal, Sync Gateway, IRT Analytics & FHIR Bridge",
    version="2.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    phone_number: str
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    caregiver_id: str
    role: str

class DeviceTokenRequest(BaseModel):
    device_id: str
    patient_id: str

class DeviceTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class MutationRequest(BaseModel):
    patient_id: str
    mutation_type: str
    payload: Dict[str, Any]
    lamport_clock: int = 1

class PushPayload(BaseModel):
    patient: Optional[Dict[str, Any]] = None
    sessions: List[Dict[str, Any]] = []
    events: List[Dict[str, Any]] = []

# In-memory alert broadcast subscribers
_alert_subscribers: List[asyncio.Queue] = []

# ─────────────────────────────────────────────────────────────────────────────
# API Endpoints
# ─────────────────────────────────────────────────────────────────────────────

@app.get("/health")
@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "smritiner_cloud",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": "embedded_sqlite_wal",
        "version": "2.0.0"
    }

# --- Authentication ---
@app.post("/portal/login", response_model=LoginResponse)
@app.post("/api/portal/login", response_model=LoginResponse)
async def portal_login(body: LoginRequest):
    caregiver = await db.authenticate_caregiver(body.phone_number)
    if not caregiver or not auth.verify_password(body.password, caregiver["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect phone number or password"
        )
    
    token = auth.create_access_token(data={
        "sub": caregiver["id"],
        "role": caregiver["role"],
        "patient_id": caregiver["patient_id"]
    })

    return LoginResponse(
        access_token=token,
        caregiver_id=caregiver["id"],
        role=caregiver["role"]
    )

@app.post("/device/token", response_model=DeviceTokenResponse)
@app.post("/api/device/token", response_model=DeviceTokenResponse)
async def device_token(body: DeviceTokenRequest):
    token = auth.create_access_token(data={
        "sub": body.device_id,
        "role": "DEVICE",
        "patient_id": body.patient_id
    })
    return DeviceTokenResponse(access_token=token)

# --- Portal Patient & Clinical Endpoints ---
@app.get("/portal/patients")
@app.get("/api/portal/patients")
async def list_patients(user: TokenData = Depends(require_role(["PRIMARY", "SECONDARY"]))):
    return await db.get_all_patients()

@app.get("/portal/patients/{id}")
@app.get("/api/portal/patients/{id}")
async def get_patient_detail(id: str, user: TokenData = Depends(require_role(["PRIMARY", "SECONDARY"]))):
    patients = await db.get_all_patients()
    for p in patients:
        if p["id"] == id:
            return p
    raise HTTPException(status_code=404, detail="Patient not found")

@app.get("/portal/patients/{id}/trend")
@app.get("/api/portal/patients/{id}/trend")
@app.get("/trend/{id}")
@app.get("/api/trend/{id}")
async def get_trend(id: str, days: int = 30, user: TokenData = Depends(require_role(["PRIMARY", "SECONDARY", "DEVICE"]))):
    return await db.get_patient_trend(id, days)

@app.get("/portal/patients/{id}/sessions")
@app.get("/api/portal/patients/{id}/sessions")
async def get_sessions(id: str, limit: int = 20, user: TokenData = Depends(require_role(["PRIMARY", "SECONDARY"]))):
    return await db.get_patient_sessions(id, limit)

@app.get("/portal/patients/{id}/sbar")
@app.get("/api/portal/patients/{id}/sbar")
@app.get("/sbar/{id}")
@app.get("/api/sbar/{id}")
async def get_sbar(id: str, user: TokenData = Depends(require_role(["PRIMARY", "SECONDARY"]))):
    patients = await db.get_all_patients()
    p = next((x for x in patients if x["id"] == id), None)
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")

    trend = await db.get_patient_trend(id, days=30)
    baseline = float(trend[0]["theta"]) if trend else float(p["baseline_theta"])
    current = float(trend[-1]["theta"]) if trend else float(p["baseline_theta"])
    sbar = irt_engine.generate_sbar_summary(p["full_name"], p["age"], baseline, current)
    return sbar

@app.get("/portal/alerts")
@app.get("/api/portal/alerts")
@app.get("/alerts/recent")
@app.get("/api/alerts/recent")
async def get_recent_alerts(user: TokenData = Depends(require_role(["PRIMARY", "SECONDARY"]))):
    alerts = await db.get_alerts()
    return {"alerts": alerts, "count": len(alerts)}

@app.get("/portal/alerts/stream")
@app.get("/api/portal/alerts/stream")
async def alerts_stream(request: Request, token: Optional[str] = None):
    """SSE stream. Accepts Authorization header or ?token= for EventSource clients."""
    credentials = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        from fastapi.security import HTTPAuthorizationCredentials
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth_header.split(" ", 1)[1])
    elif token:
        from fastapi.security import HTTPAuthorizationCredentials
        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

    if credentials:
        try:
            await auth.get_current_user(credentials)
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid stream token")

    async def event_stream():
        queue = asyncio.Queue()
        _alert_subscribers.append(queue)
        try:
            yield "event: connected\ndata: {\"status\":\"connected\"}\n\n"
            while True:
                data = await queue.get()
                yield f"event: alert\ndata: {json.dumps(data)}\n\n"
        except asyncio.CancelledError:
            if queue in _alert_subscribers:
                _alert_subscribers.remove(queue)

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.post("/portal/caregiver/mutations", status_code=201)
@app.post("/api/portal/caregiver/mutations", status_code=201)
@app.post("/mutations", status_code=201)
@app.post("/api/mutations", status_code=201)
async def create_mutation(body: MutationRequest, user: TokenData = Depends(require_role(["PRIMARY", "SECONDARY"]))):
    conn = await db.get_db()
    try:
        now = datetime.now(timezone.utc).isoformat()
        mut_id = f"mut_{int(datetime.now().timestamp())}"
        await conn.execute("""
            INSERT INTO caregiver_mutations (id, patient_id, caregiver_id, mutation_type, payload, lamport_clock, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (mut_id, body.patient_id, user.user_id, body.mutation_type, json.dumps(body.payload), body.lamport_clock, now))
        await conn.commit()
        return {"mutation_id": mut_id, "status": "queued"}
    finally:
        await conn.close()

# --- Mobile Device Sync Gateway Endpoints ---
@app.post("/push")
@app.post("/api/push")
@app.post("/sync/events")
@app.post("/api/sync/events")
async def push_sync(body: PushPayload, user: TokenData = Depends(require_role(["DEVICE", "PRIMARY", "SECONDARY"]))):
    """Accept mobile elder push payloads (and legacy portal shapes)."""
    conn = await db.get_db()
    try:
        now = datetime.now(timezone.utc)
        synced_sessions = 0
        synced_events = 0
        affected_patients: Dict[str, Tuple[float, Optional[float]]] = {}

        # Upsert patient metadata when provided by the device
        if body.patient and body.patient.get("id"):
            await db.upsert_patient(conn, body.patient)

        # Upsert Sessions — accept both mobile and legacy field names
        for s in body.sessions:
            sess_id = s.get("session_id", f"sess_{int(now.timestamp())}_{synced_sessions}")
            pat_id = (
                s.get("patient_id")
                or (body.patient or {}).get("id")
                or user.patient_id
                or "00000000-0000-0000-0000-000000000001"
            )

            responses = s.get("responses", [])
            if responses:
                theta_val, sem = irt_engine.estimate_theta_eap(responses)
            else:
                theta_val = float(s.get("final_theta", s.get("initial_theta", 0.0)) or 0.0)
                sem = float(s.get("sem", 0.28) or 0.28)

            started_at = s.get("start_time") or s.get("started_at") or now.isoformat()
            completed_at = s.get("end_time") or s.get("completed_at") or now.isoformat()
            items_attempted = int(
                s.get("total_trials")
                if s.get("total_trials") is not None
                else s.get("items_attempted", 0) or 0
            )
            items_correct = int(
                s.get("successful_trials")
                if s.get("successful_trials") is not None
                else s.get("items_correct", 0) or 0
            )

            # Capture prior baseline before overwriting (for decline alerts)
            prior_baseline = await db.get_patient_theta(conn, pat_id)

            await conn.execute("""
                INSERT OR REPLACE INTO sessions (
                    session_id, patient_id, game_type, started_at, completed_at,
                    items_attempted, items_correct, final_theta, sem
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                sess_id, pat_id, s.get("game_type", "SMRITI_UDYAN"),
                started_at, completed_at,
                items_attempted, items_correct,
                theta_val, sem,
            ))
            synced_sessions += 1
            affected_patients[pat_id] = (theta_val, prior_baseline)

            await db.upsert_daily_theta_rollup(conn, pat_id, started_at, theta_val)
            await db.update_patient_theta(conn, pat_id, theta_val, now.isoformat())

        # Upsert Telemetry Events — accept event_id/payload/timestamp_utc from mobile
        for ev in body.events:
            ev_id = (
                ev.get("event_id")
                or ev.get("id")
                or f"ev_{int(now.timestamp())}_{synced_events}"
            )
            pat_id = (
                ev.get("patient_id")
                or (body.patient or {}).get("id")
                or user.patient_id
                or "00000000-0000-0000-0000-000000000001"
            )
            event_payload = ev.get("payload")
            if event_payload is None:
                event_payload = ev.get("event_data", {})
            if not isinstance(event_payload, (dict, list)):
                event_payload = {"raw": event_payload}

            await conn.execute("""
                INSERT OR REPLACE INTO patient_telemetry_events (
                    id, session_id, patient_id, event_type, event_data, recorded_at
                ) VALUES (?, ?, ?, ?, ?, ?)
            """, (
                ev_id,
                ev.get("session_id", "sess_0"),
                pat_id,
                ev.get("event_type", "TOUCH_LATENCY"),
                json.dumps(event_payload),
                ev.get("timestamp_utc") or ev.get("recorded_at") or now.isoformat(),
            ))
            synced_events += 1

        # Clinical alerts for sharp theta drops vs prior baseline
        for pat_id, (new_theta, prior_baseline) in affected_patients.items():
            alert = await db.maybe_create_decline_alert(
                conn, pat_id, new_theta, now.isoformat(), prior_baseline=prior_baseline
            )
            if alert:
                for queue in list(_alert_subscribers):
                    try:
                        queue.put_nowait(alert)
                    except Exception:
                        pass

        await conn.commit()
        return {
            "synced_sessions": synced_sessions,
            "synced_events": synced_events,
            "server_timestamp": now.isoformat(),
            "status": "success",
        }
    finally:
        await conn.close()

@app.get("/pull/{patient_id}")
@app.get("/api/pull/{patient_id}")
async def pull_mutations(patient_id: str, since_lamport: int = 0, user: TokenData = Depends(require_role(["DEVICE", "PRIMARY", "SECONDARY"]))):
    conn = await db.get_db()
    try:
        async with conn.execute(
            "SELECT * FROM caregiver_mutations WHERE patient_id = ? AND lamport_clock > ? ORDER BY lamport_clock ASC",
            (patient_id, since_lamport)
        ) as cursor:
            rows = await cursor.fetchall()
            mutations = [dict(r) for r in rows]
            latest_clock = max([m["lamport_clock"] for m in mutations], default=since_lamport)
            return {"mutations": mutations, "latest_lamport_clock": latest_clock}
    finally:
        await conn.close()

# --- FHIR ABDM Endpoints ---
@app.get("/fhir/DiagnosticReport/{patient_id}")
@app.get("/api/fhir/DiagnosticReport/{patient_id}")
async def fhir_diagnostic_report(patient_id: str):
    patients = await db.get_all_patients()
    p = next((x for x in patients if x["id"] == patient_id), None)
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")
    
    return {
        "resourceType": "DiagnosticReport",
        "id": f"sih-dr-{patient_id[:8]}",
        "status": "final",
        "category": [{
            "coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                "code": "MB",
                "display": "Cognitive Screening Battery"
            }]
        }],
        "code": {
            "coding": [{
                "system": "http://loinc.org",
                "code": "72106-8",
                "display": "Cognitive Assessment Panel"
            }]
        },
        "subject": {
            "reference": f"Patient/{patient_id}",
            "display": p["full_name"]
        },
        "effectiveDateTime": datetime.now(timezone.utc).isoformat(),
        "conclusion": f"SmritiNER IRT 2-PL Cognitive Ability Index θ = {p['baseline_theta']:.2f}. Status: {p['status']}."
    }

# ─────────────────────────────────────────────────────────────────────────────
# Static Assets & APK Download Handling
# ─────────────────────────────────────────────────────────────────────────────
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
APK_PATH = os.path.join(STATIC_DIR, "downloads", "smritiner-elder-app.apk")

@app.get("/downloads/smritiner-elder-app.apk")
@app.get("/api/downloads/smritiner-elder-app.apk")
async def download_apk():
    if os.path.exists(APK_PATH):
        return FileResponse(
            path=APK_PATH,
            filename="smritiner-elder-app.apk",
            media_type="application/vnd.android.package-archive"
        )
    raise HTTPException(status_code=404, detail="APK binary not found")

# Mount static files (assets, favicon, etc.)
if os.path.exists(STATIC_DIR):
    assets_path = os.path.join(STATIC_DIR, "assets")
    if os.path.exists(assets_path):
        app.mount("/assets", StaticFiles(directory=assets_path), name="assets")

# Catch-all Single Page Application (SPA) Router
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    # Check if a static file directly exists
    file_path = os.path.join(STATIC_DIR, full_path)
    if full_path and os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
    
    # Fallback to index.html for React Router
    index_file = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    
    return JSONResponse(
        status_code=200,
        content={"message": "SmritiNER Cloud API running. Frontend static build pending."}
    )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8090))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
