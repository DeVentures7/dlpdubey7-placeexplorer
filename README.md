# 🗺️ PlaceExplorer

**AI-powered outing planner.** Answer a few questions and get a timed day plan with real road travel times between stops.

> ⚠️ Development-stage portfolio project, not production software.

Repo: https://github.com/DeVentures7/dlpdubey7-placeexplorer

## What it does

1. Pick a destination (auto-detected from your location or searched).
2. Choose Half/Full day, Morning/Evening, one interest (Temples, Nature, Heritage, Shopping) and food preference.
3. Get an itinerary with:
   - Timed stops and visit durations
   - Road distance/time to the next stop
   - Nearby restaurants and "worth a detour" places
4. Tap any stop for details, opening hours (if available) and navigation.

There is also a chat agent (`/api/agent/chat`) that answers questions using Gemini + live map data.

## Tech stack

| Part | Technology |
|---|---|
| Android app | Kotlin, Jetpack Compose, MVVM, Retrofit |
| Backend | Python, FastAPI |
| AI | Gemini (text, function calling, embeddings), RAG, MCP tools |
| Map data | OpenStreetMap: Nominatim (geocoding), Overpass (places), OSRM (routing) |

## How it works

```
Android app → FastAPI backend → MCP tools → Overpass / OSRM
                    ↓
              Gemini + RAG (travel guides)
```

- Places are found on OpenStreetMap, ranked by distance and popularity.
- OSRM gives real road times; stops are ordered nearest-first and fitted into the outing window.
- If data or routing is unavailable, the app returns an error instead of making things up.

## Run the backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env             # add your GEMINI_API_KEY
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: `http://localhost:8000/docs`

## Run the Android app

1. Open `android_mobile_app/PlaceExplorer` in Android Studio.
2. Set `API_BASE_URL` in `app/build.gradle.kts`:
   - Emulator: `http://10.0.2.2:8000/`
   - Real device: `http://<your-PC-IP>:8000/`
3. Run the `app` configuration and allow location permission.

Set `DevelopmentConfig.useApiRepository = false` to use mock data without a backend.

## Main API endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/plan` | Generate itinerary |
| POST | `/api/agent/chat` | Chat agent |
| GET | `/api/places/search` | Search places |
| GET | `/api/places/{place_id}` | Place details + nearby spots |
| GET | `/api/geocode` | Search destination |

## Tests

```bash
cd backend && pytest tests/ -q    # 122 tests
cd android_mobile_app/PlaceExplorer && ./gradlew testDebugUnitTest
```

## Known limitations

- Uses free public OSM services, so rate limits and timeouts can happen.
- OSM data is often missing hours or food details; the app shows "unknown".
- RAG uses an in-memory store and a small knowledge base (only the Goa guide has content).
- Single interest per plan, one-day trips only, no saved history.
- No auth, HTTPS or Docker; for local development only.

## Roadmap

Persistent vector store (ChromaDB) · Hilt · multi-day trips · live "open now" data · Docker and production hardening

## License

No license file yet. Add one (e.g., MIT) before sharing publicly.

---
*Map data © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors.*
