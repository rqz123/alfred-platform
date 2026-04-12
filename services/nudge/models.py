from typing import Optional, Literal
from pydantic import BaseModel


class ParseRequest(BaseModel):
    input: str
    timezone: str


class ParsedReminder(BaseModel):
    title: str
    body: Optional[str] = None
    type: Literal["once", "recurring", "event"]
    fireAt: Optional[str] = None
    cronExpression: Optional[str] = None
    timezone: str


class ParseResponse(BaseModel):
    reminder: ParsedReminder
    confidence: float
    rawInterpretation: str


class ReminderCreate(BaseModel):
    title: str
    body: Optional[str] = None
    type: Literal["once", "recurring", "event"]
    fireAt: Optional[str] = None
    cronExpression: Optional[str] = None
    timezone: str
    triggerSource: Optional[str] = None
    triggerCondition: Optional[dict] = None


class ReminderOut(BaseModel):
    id: str
    title: str
    body: Optional[str] = None
    type: str
    fireAt: Optional[str] = None
    cronExpression: Optional[str] = None
    timezone: str
    triggerSource: Optional[str] = None
    triggerCondition: Optional[dict] = None
    status: str
    lastFiredAt: Optional[str] = None
    nextFireAt: Optional[str] = None
    createdAt: str
    updatedAt: str
