# app/routers/api_key.py
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app import database, models, schemas
from app.crud import api_key as crud
from app.dependencies.permission import require

router = APIRouter(prefix="/api/api-keys", tags=["API Keys"])


@router.post("/v1/api-key/", status_code=status.HTTP_201_CREATED, response_model=schemas.APIKeyCreated,
             summary="Create an API key - the plaintext `key` is returned ONLY in this response")
def create_api_key(body: schemas.APIKeyCreate, request: Request, db: Session = Depends(database.get_db),
                   current_user: models.User = require("create_api_key")):
    key, plaintext = crud.create_api_key(db, request, current_user, body)
    return schemas.APIKeyCreated(**schemas.APIKeyOut.model_validate(key).model_dump(), key=plaintext)


@router.get("/v1/api-key/", response_model=schemas.APIKeyListResponse, dependencies=[require("read_api_key")])
def list_api_keys(is_active: bool | None = None, customer_id: str | None = Query(None, max_length=100),
                  include_deleted: bool = False, skip: int = 0, limit: int = Query(10, ge=1, le=200),
                  db: Session = Depends(database.get_db)):
    items, total = crud.list_api_keys(db, is_active=is_active, customer_id=customer_id,
                                      include_deleted=include_deleted, skip=skip, limit=limit)
    return {"status": "success",
            "result": {"count": total, "data": [schemas.APIKeyOut.model_validate(k) for k in items]}}


@router.get("/v1/api-key/{id}", response_model=schemas.APIKeyOut, dependencies=[require("read_api_key")])
def get_api_key(id: int, db: Session = Depends(database.get_db)):
    return crud.get_api_key(db, id)


@router.patch("/v1/api-key/{id}", response_model=schemas.APIKeyOut)
def update_api_key(id: int, body: schemas.APIKeyUpdate, request: Request, db: Session = Depends(database.get_db),
                   current_user: models.User = require("update_api_key")):
    return crud.update_api_key(db, request, current_user, id, body)


@router.post("/v1/api-key/{id}/revoke", response_model=schemas.APIKeyOut, summary="Revoke a key (irreversible)")
def revoke_api_key(id: int, request: Request, db: Session = Depends(database.get_db),
                   current_user: models.User = require("update_api_key")):
    return crud.revoke_api_key(db, request, current_user, id)


@router.delete("/v1/api-key/{id}", status_code=status.HTTP_200_OK)
def delete_api_key(id: int, request: Request, db: Session = Depends(database.get_db),
                   current_user: models.User = require("delete_api_key")):
    """Soft delete (also revokes) the key."""
    crud.delete_api_key(db, request, current_user, id)
    return {"message": "API key deleted"}
