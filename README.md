# 🧠 SmritiNER Cloud — All-in-One 24/7 Hosted Service

This folder contains the **complete, self-contained cloud deployment package** for SmritiNER.

It unifies:
1. **Caregiver Web Portal (React + Tailwind)**: Pre-compiled with authentication guards, clinical sparklines, and patient cards.
2. **FastAPI Sync Gateway**: Complete REST API for mobile app delta-sync, JWT authentication, and clinical alert streams.
3. **Embedded SQLite Database**: Pre-seeded with 30-day clinical trajectories for all 3 personas (**Biren Da**, **Kong Mary**, **Subedar Thapa**) and demo caregiver login (`+919876543210` / `demo123`).
4. **Android Release APK**: Pre-packaged for 1-tap download and QR code scanning at `/downloads/smritiner-elder-app.apk`.
5. **Cognitive IRT Math Engine & ABDM FHIR Bridge**: Real-time Bayesian ability estimation and HL7 FHIR DiagnosticReport generation.

---

## 🚀 3-Minute Deployment to Render.com (100% Free • No Credit Card Required)

### Step 1: Create a GitHub Repository
1. Go to [github.com/new](https://github.com/new).
2. Name your repository `smritiner-cloud` and select **Public** (or Private).
3. Open a terminal in this `smritiner_cloud` directory and run:

```powershell
cd d:\SIH_PROJECT_2\SIH_PROJECT_2\smritiner_cloud
git init
git add .
git commit -m "Deploy SmritiNER All-in-One Cloud Stack"
git branch -M main
git remote add origin https://github.com/<your-username>/smritiner-cloud.git
git push -u origin main
```

---

### Step 2: Deploy on Render.com (1 Click)
1. Go to **[render.com](https://render.com)** and sign in with your GitHub account *(no credit card asked)*.
2. Click **New +** in the top right → Select **Web Service**.
3. Connect your **`smritiner-cloud`** repository.
4. Fill in the settings:
   - **Name**: `smritiner` (or any name you choose)
   - **Language**: `Python 3`
   - **Branch**: `main`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type**: **Free** ($0 / month)
5. Click **Create Web Service**!

---

## 🌐 What You Get Once Deployed
Within 1–2 minutes, Render will assign you a permanent 24/7 HTTPS domain:

* **Caregiver Portal**: `https://<your-service>.onrender.com`
* **Direct APK Download**: `https://<your-service>.onrender.com/downloads/smritiner-elder-app.apk`
* **Backend API Health**: `https://<your-service>.onrender.com/health`

### Split deploy (Vercel frontend + Render API)
1. Set Vercel env `VITE_API_URL` to your Render URL (example: `https://smritiner.onrender.com`) and redeploy.
2. Rebuild the Android APK with  
   `flutter build apk --release --dart-define=SYNC_GATEWAY_URL=https://<your-service>.onrender.com`
3. If your Render hostname is not `smritiner.onrender.com`, update that URL in:
   - `smritiner/web/caregiver_portal/.env.production`
   - `smritiner/apps/mobile_elder/lib/core/constants.dart` (`productionSyncGatewayUrl`)
   - Vercel rewrite destinations for APK downloads

### 🔑 Demo Caregiver Login:
* **Phone Number / ID**: `+919876543210` (or `9876543210`)
* **Password**: `demo123`

---

## 🔄 How to Update the Frontend Later
Whenever you make changes to the React code or Python API:
1. Re-build or edit the files in `smritiner_cloud/`.
2. Run `git commit -am "Update UI"` and `git push`.
3. Render will automatically detect the push and redeploy your live site within 60 seconds!
