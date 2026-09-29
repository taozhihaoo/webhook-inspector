"""Development / demo mock receiver (NOT a production feature).

Gives the demo a safe replay target so the full loop can be shown locally:
webhook -> capture -> inspect -> modify -> replay -> receiver.
It keeps an in-memory history of what it received (lost on restart) and is
only mounted when ENABLE_MOCK_RECEIVER=true (default outside production).
"""

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from app.schemas import DeleteOut, Envelope
from app.util import decode_lossy, utcnow

router = APIRouter()

MAX_RECORDED_BODY = 10_000


@router.api_route("/mock/receiver", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def mock_receiver(request: Request) -> JSONResponse:
    body = await request.body()
    entry = {
        "received_at": utcnow().isoformat(),
        "method": request.method,
        "path": request.url.path,
        "query_parameters": dict(request.query_params),
        "headers": dict(request.headers),
        "body_size": len(body),
        "body_text": decode_lossy(body)[:MAX_RECORDED_BODY],
    }
    request.app.state.mock_history.appendleft(entry)
    return JSONResponse(
        {"received": True, "echo": {"method": entry["method"], "body_bytes": len(body)}}
    )


@router.get("/mock/receiver/requests")
async def mock_history(request: Request) -> Envelope[list[dict]]:
    return Envelope(data=list(request.app.state.mock_history))


@router.delete("/mock/receiver/requests")
async def clear_mock_history(request: Request) -> Envelope[DeleteOut]:
    request.app.state.mock_history.clear()
    return Envelope(data=DeleteOut(deleted=True, count=0))
