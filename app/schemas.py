"""Pydantic schemas for request/response serialization."""
from datetime import datetime
from pydantic import BaseModel, Field


# ─── Extensions ───────────────────────────────────────────────────────────────

class ExtensionOut(BaseModel):
    id: str
    ehr_user_id: str
    extension_number: str
    display_name: str
    voip_role: str
    staff_category: str | None
    presence_status: str
    is_active: bool

    model_config = {'from_attributes': True}


class ExtensionCreate(BaseModel):
    ehr_user_id: str
    extension_number: str
    display_name: str
    voip_role: str
    staff_category: str | None = None


class PresenceUpdate(BaseModel):
    status: str = Field(..., pattern='^(available|away|dnd|offline)$')


# ─── Calls ────────────────────────────────────────────────────────────────────

class CallLogOut(BaseModel):
    id: str
    direction: str
    remote_number: str
    contact_name: str | None
    started_at: datetime
    answered_at: datetime | None
    ended_at: datetime | None
    duration: int
    disposition: str
    recording_url: str | None
    has_recording: bool
    note: str | None

    model_config = {'from_attributes': True}


class CallNoteIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


class HoldIn(BaseModel):
    channel: str   # Asterisk channel string


class TransferIn(BaseModel):
    channel: str
    destination: str    # extension number
    attended: bool = False


# ─── Voicemail ────────────────────────────────────────────────────────────────

class VoicemailOut(BaseModel):
    id: str
    caller_number: str
    caller_name: str | None
    received_at: datetime
    duration: int
    audio_url: str
    transcription: str | None
    listened: bool
    extension_id: str

    model_config = {'from_attributes': True}


# ─── SMS ──────────────────────────────────────────────────────────────────────

class SmsThreadOut(BaseModel):
    id: str
    external_number: str
    contact_name: str | None
    last_message_at: datetime
    last_message_body: str
    unread_count: int
    assigned_to_id: str | None
    assigned_to_name: str | None
    status: str

    model_config = {'from_attributes': True}


class SmsMessageOut(BaseModel):
    id: str
    thread_id: str
    direction: str
    body: str
    sent_at: datetime
    sent_by_id: str | None
    sender_name: str | None
    status: str

    model_config = {'from_attributes': True}


class SmsSendIn(BaseModel):
    to_number: str = Field(..., pattern=r'^\+1\d{10}$')
    body: str = Field(..., min_length=1, max_length=1600)
    thread_id: str | None = None


class SmsAssignIn(BaseModel):
    extension_id: str


# ─── Push tokens ──────────────────────────────────────────────────────────────

class PushTokenIn(BaseModel):
    token: str
    platform: str = Field(..., pattern='^(ios|android)$')
    is_voip_push: bool = False


# ─── Routing ──────────────────────────────────────────────────────────────────

class RoutingRuleOut(BaseModel):
    id: str
    name: str
    priority: int
    schedule_type: str
    destination_type: str
    destination_value: str
    is_enabled: bool

    model_config = {'from_attributes': True}


class RoutingRuleIn(BaseModel):
    name: str
    priority: int = 10
    schedule_type: str
    destination_type: str
    destination_value: str
    is_enabled: bool = True


# ─── Presence WebSocket ───────────────────────────────────────────────────────

class PresenceWSMessage(BaseModel):
    type: str               # presence_update
    extension_id: str
    user_id: str
    display_name: str
    status: str
    current_call_id: str | None = None
