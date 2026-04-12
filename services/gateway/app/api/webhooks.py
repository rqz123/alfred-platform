from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlmodel import Session

from app.core.config import get_settings
from app.db.session import get_session
from app.services.whatsapp_service import process_webhook_payload, verify_webhook_request


webhook_router = APIRouter(tags=["webhooks"])


@webhook_router.get("/webhooks/whatsapp")
def verify_webhook(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> Response:
    settings = get_settings()
    is_valid = (
        hub_mode == "subscribe"
        and hub_verify_token == settings.whatsapp_verify_token
        and hub_challenge is not None
    )
    if not is_valid:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid verify token")

    return Response(content=hub_challenge, media_type="text/plain")


@webhook_router.post("/webhooks/whatsapp", status_code=status.HTTP_200_OK)
async def receive_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    body = await request.body()
    verify_webhook_request(body, x_hub_signature_256)
    payload = await request.json()
    process_webhook_payload(session, payload)
    return {"status": "received"}