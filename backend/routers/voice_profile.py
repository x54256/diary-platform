"""用户热词与人物关系管理接口。"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import get_db
from models.user import User
from models.voice_profile import HotWord, PersonRelation
from schemas.voice_profile import (
    HotWordCreate,
    HotWordResponse,
    PersonRelationCreate,
    PersonRelationResponse,
)
from services.auth import get_current_user

router = APIRouter(prefix="/api", tags=["用户资料"])
logger = logging.getLogger("voice_profile.api")


def _duplicate_error(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _get_hot_word(db: Session, item_id: UUID, user_id: UUID) -> HotWord:
    item = db.query(HotWord).filter(HotWord.id == item_id, HotWord.user_id == user_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="热词不存在")
    return item


def _get_person(db: Session, item_id: UUID, user_id: UUID) -> PersonRelation:
    item = db.query(PersonRelation).filter(PersonRelation.id == item_id, PersonRelation.user_id == user_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="人物关系不存在")
    return item


def _validate_person_names(
    db: Session,
    user_id: UUID,
    name: str,
    common_names: list[str],
    exclude_id: UUID | None = None,
) -> None:
    """保证同一用户的人物姓名和常用名不会互相冲突。"""
    candidate = [name, *common_names]
    candidate_keys = [value.casefold() for value in candidate]
    if len(candidate_keys) != len(set(candidate_keys)):
        raise _duplicate_error("姓名和常用名不能重复")

    query = db.query(PersonRelation).filter(PersonRelation.user_id == user_id)
    if exclude_id:
        query = query.filter(PersonRelation.id != exclude_id)
    existing = query.all()
    occupied: set[str] = set()
    for person in existing:
        occupied.add(person.name.casefold())
        occupied.update(value.casefold() for value in (person.common_names or []))
    if occupied.intersection(candidate_keys):
        raise _duplicate_error("姓名或常用名已被其他人物使用")


@router.get("/hot-words", response_model=list[HotWordResponse])
def list_hot_words(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(HotWord).filter(HotWord.user_id == current_user.id).order_by(HotWord.created_at.desc()).all()


@router.post("/hot-words", response_model=HotWordResponse, status_code=201)
def create_hot_word(payload: HotWordCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    key = payload.text.casefold()
    exists = db.query(HotWord).filter(HotWord.user_id == current_user.id).all()
    if any(item.text.casefold() == key for item in exists):
        raise _duplicate_error("热词已存在")
    item = HotWord(user_id=current_user.id, text=payload.text)
    db.add(item)
    try:
        db.commit()
        db.refresh(item)
    except IntegrityError:
        db.rollback()
        raise _duplicate_error("热词已存在")
    return item


@router.put("/hot-words/{item_id}", response_model=HotWordResponse)
def update_hot_word(item_id: UUID, payload: HotWordCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = _get_hot_word(db, item_id, current_user.id)
    exists = db.query(HotWord).filter(HotWord.user_id == current_user.id, HotWord.id != item.id).all()
    if any(other.text.casefold() == payload.text.casefold() for other in exists):
        raise _duplicate_error("热词已存在")
    item.text = payload.text
    try:
        db.commit()
        db.refresh(item)
    except IntegrityError:
        db.rollback()
        raise _duplicate_error("热词已存在")
    return item


@router.delete("/hot-words/{item_id}", status_code=204)
def delete_hot_word(item_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = _get_hot_word(db, item_id, current_user.id)
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@router.get("/person-relations", response_model=list[PersonRelationResponse])
def list_person_relations(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(PersonRelation).filter(PersonRelation.user_id == current_user.id).order_by(PersonRelation.created_at.desc()).all()


@router.post("/person-relations", response_model=PersonRelationResponse, status_code=201)
def create_person_relation(payload: PersonRelationCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _validate_person_names(db, current_user.id, payload.name, payload.common_names)
    item = PersonRelation(user_id=current_user.id, **payload.model_dump())
    db.add(item)
    try:
        db.commit()
        db.refresh(item)
    except IntegrityError:
        db.rollback()
        raise _duplicate_error("姓名或常用名已存在")
    return item


@router.put("/person-relations/{item_id}", response_model=PersonRelationResponse)
def update_person_relation(item_id: UUID, payload: PersonRelationCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = _get_person(db, item_id, current_user.id)
    _validate_person_names(db, current_user.id, payload.name, payload.common_names, exclude_id=item.id)
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    try:
        db.commit()
        db.refresh(item)
    except IntegrityError:
        db.rollback()
        raise _duplicate_error("姓名或常用名已存在")
    return item


@router.delete("/person-relations/{item_id}", status_code=204)
def delete_person_relation(item_id: UUID, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    item = _get_person(db, item_id, current_user.id)
    db.delete(item)
    db.commit()
    return Response(status_code=204)
