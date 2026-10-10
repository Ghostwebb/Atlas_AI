"""ATLAS AI backend entrypoint (Phase 2: demo dataset + deterministic engine)."""

import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.analysis.service import analyze_symbol
from app.data.demo_provider import DemoDataProvider
from app.data.provider import MarketDataProvider
from app.schemas import AnalyzeRequest, AnalyzeResponse, ErrorResponse
from app.supervision.models import SupervisionIntegrityError
from app.symbols import is_valid_format

SERVICE_NAME = "atlas-ai-backend"
INVALID_SYMBOL_ERROR = "Invalid stock symbol"
INVALID_SYMBOL_MESSAGE = "Please provide a valid stock symbol."

# Swap this provider for a real one in later phases; routes do not change.
market_data_provider: MarketDataProvider = DemoDataProvider()

app = FastAPI(title="ATLAS AI Backend", version="0.2.0")

_allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "ATLAS_CORS_ORIGINS", "http://localhost:3000"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


def _invalid_symbol_response(status_code: int) -> JSONResponse:
    body = ErrorResponse(error=INVALID_SYMBOL_ERROR, message=INVALID_SYMBOL_MESSAGE)
    return JSONResponse(status_code=status_code, content=body.model_dump())


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": SERVICE_NAME}


@app.exception_handler(RequestValidationError)
async def _request_validation_handler(
    _: Request, __: RequestValidationError
) -> JSONResponse:
    # Malformed bodies (missing field, wrong type, too long, extra keys)
    # are reported with the same error contract as invalid symbols.
    return _invalid_symbol_response(400)


@app.post(
    "/api/analyze",
    response_model=AnalyzeResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def analyze(payload: AnalyzeRequest) -> AnalyzeResponse | JSONResponse:
    # Format is checked first (400); existence second (404).
    if not is_valid_format(payload.symbol):
        return _invalid_symbol_response(400)

    try:
        result = analyze_symbol(payload.symbol, market_data_provider)
    except SupervisionIntegrityError as error:
        # Invalid or inconsistent computed data: no reliable report can be issued.
        body = ErrorResponse(
            error="Supervision integrity error",
            message="The analysis could not be verified and no report was produced.",
        )
        return JSONResponse(status_code=500, content=body.model_dump())
    if result is None:
        return _invalid_symbol_response(404)
    return result
