"""The public webhook receiver: ANY /hook/{public_id}."""

from fastapi import APIRouter, Request

from app.services.ingest_service import handle_ingest

router = APIRouter()

METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]


@router.api_route("/hook/{public_id}", methods=METHODS, include_in_schema=False)
async def receive_webhook(public_id: str, request: Request):
    return await handle_ingest(request.app.state, request, public_id)
