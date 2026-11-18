
import os

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from google import genai
from app.agent.mcp_agent import run_agent
from app.schemas.geocoding import GeoReverseResponse, GeoSearchResponse
from app.schemas.outing import Itinerary, OutingRequest, PlaceDetailsResponse
from app.services.itinerary_generator import (
    DestinationNotFoundError,
    InsufficientPlacesError,
    generate_itinerary,
)
from app.services.place_details_service import (
    PlaceNotFoundError,
    build_place_details,
    search_places_for_query,
)
from app.tools.geocode_tools import search_location, reverse_geocode

# Load environment variables from .env
load_dotenv()

# Read Gemini configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing from .env")

# Initialize Gemini client
client = genai.Client(api_key=GEMINI_API_KEY)

# Create FastAPI application
app = FastAPI(
    title="PlaceExplorer AI Backend",
    description="AI-powered place discovery assistant",
    version="0.1.0"
)


# Request model
class ChatRequest(BaseModel):
    message: str


# Health-check endpoint
@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "application": "PlaceExplorer Backend"
    }


# Gemini test endpoint
@app.post("/api/chat")
def chat(request: ChatRequest):

    if not request.message.strip():
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty"
        )

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=request.message
        )

        return {
            "query": request.message,
            "response": response.text
        }

    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Unable to get a response from Gemini"
        )


@app.post("/api/agent/chat")
async def agent_chat(request: ChatRequest):

    if not request.message.strip():
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty"
        )

    try:
        answer = await run_agent(
            message=request.message,
            client=client,
            model=GEMINI_MODEL
        )

        return {
            "query": request.message,
            "response": answer
        }

    except Exception as error:
        print(f"Agent error: {error}")
        raise HTTPException(
            status_code=502,
            detail="Unable to process the Agent request"
        )


# Geocoding endpoint: resolve manually entered city names, localities,
# landmarks and addresses into real coordinates (OSM Nominatim).
# The Android client searches on intentional submission or debounced
# input, never on every keystroke (Nominatim usage policy).
@app.get("/api/geocode", response_model=GeoSearchResponse)
def geocode(
    q: str = Query(..., description="Free-text place search query"),
    limit: int = Query(5, ge=1, le=10, description="Maximum results (1-10)"),
) -> GeoSearchResponse:

    result = search_location(q, limit=limit)

    if "error" in result:
        # Validation errors are client problems; provider problems are
        # upstream trouble the client should retry later.
        status_code = 400 if "must not be empty" in result["error"] or "limit must" in result["error"] else 502
        raise HTTPException(status_code=status_code, detail=result["error"])

    return result


# Reverse geocoding endpoint: label device coordinates as a city / place
# (OSM Nominatim Reverse). Used by the Android app to default the
# destination to the user's current city.
@app.get("/api/geocode/reverse", response_model=GeoReverseResponse)
def geocode_reverse(
    latitude: float = Query(..., description="Device latitude"),
    longitude: float = Query(..., description="Device longitude"),
) -> GeoReverseResponse:

    result = reverse_geocode(latitude, longitude)

    if "error" in result:
        status_code = (
            400 if "must be between" in result["error"] else 502
        )
        raise HTTPException(status_code=status_code, detail=result["error"])

    return result


# Structured outing-planning endpoint for the Android app.
@app.post("/api/plan", response_model=Itinerary)
async def plan_outing(outing_request: OutingRequest) -> Itinerary:

    try:
        itinerary = await generate_itinerary(
            request=outing_request,
            client=client,
            model=GEMINI_MODEL
        )

        return itinerary

    except DestinationNotFoundError as error:
        # A destination Nominatim cannot resolve is a client-input problem.
        raise HTTPException(status_code=400, detail=str(error))

    except InsufficientPlacesError as error:
        # Not enough real place data: never fabricate coordinates,
        # ratings or opening hours.
        print(f"Plan error: {error}")
        raise HTTPException(status_code=503, detail=str(error))

    except HTTPException:
        raise

    except Exception as error:
        print(f"Plan error: {error}")
        raise HTTPException(
            status_code=502,
            detail="Unable to generate the itinerary"
        )


# Free-text place search for the Android app: resolves the query to a
# center (Nominatim) or uses the given coordinates, then searches real
# OSM places around it, ranked by distance + popularity.
@app.get("/api/places/search")
async def places_search(
    q: str = Query(..., description="Free-text place search query"),
    latitude: float | None = Query(None, description="Optional search center latitude"),
    longitude: float | None = Query(None, description="Optional search center longitude"),
    radius_km: float = Query(15.0, gt=0, le=80, description="Search radius in km"),
    category: str | None = Query(
        None, description="Optional canonical category filter"
    ),
) -> dict:

    try:
        places, error = await search_places_for_query(
            query=q,
            latitude=latitude,
            longitude=longitude,
            radius_km=radius_km,
            category=category,
        )
    except Exception as error:
        print(f"Place search error: {error}")
        raise HTTPException(
            status_code=502,
            detail="Unable to search places"
        )

    if error is not None:
        # The query could not be geocoded: a client-input problem.
        raise HTTPException(status_code=400, detail=error)

    return {
        "query": q,
        "total_results": len(places),
        "places": places,
    }


# Place details for the Android details screen: the itinerary passes the
# selected place's actual OSM id; the backend resolves that exact id -
# never a new search that could fail to resolve the same place - and adds
# nearby cafes/restaurants and nearby famous places around its real
# coordinates.
@app.get("/api/places/{place_id:path}", response_model=PlaceDetailsResponse)
async def place_details(
    place_id: str,
    food_preference: str | None = Query(
        None,
        alias="foodPreference",
        description="VEGETARIAN / NON_VEGETARIAN / BOTH - filters nearby food",
    ),
) -> PlaceDetailsResponse:

    if not place_id.strip():
        raise HTTPException(status_code=400, detail="place_id must not be empty")

    try:
        return await build_place_details(place_id, food_preference=food_preference)
    except PlaceNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error))
    except Exception as error:
        print(f"Place details error: {error}")
        raise HTTPException(
            status_code=502,
            detail="Unable to load place details"
        )
