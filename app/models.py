"""SQLAlchemy ORM models for Dymphna VoIP service."""
import uuid
from datetime import datetime
from sqlalchemy import (
    String, Integer, Boolean, DateTime, Text, ForeignKey,
    Enum as SAEnum, Index,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from .database import Base

# ─── Helpers ──────────────────────────────────────────────────────────────────

def gen_uuid():
    return str(uuid.uuid4())

# ─── Extensions ───────────────────────────────────────────────────────────────

class Extension(Base):
    __tablename__ = 'voip_extensions'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    ehr_user_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    extension_number: Mapped[str] = mapped_column(String(10), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100))
    voip_role: Mapped[str] = mapped_column(String(30))
    staff_category: Mapped[str | None] = mapped_column(String(30), nullable=True)
    sip_password: Mapped[str] = mapped_column(String(100))
    forwarding_number: Mapped[str | None] = mapped_column(String(20), nullable=True)  # staff cell for click-to-call
    presence_status: Mapped[str] = mapped_column(String(20), default='offline')
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    push_tokens: Mapped[list['PushToken']] = relationship('PushToken', back_populates='extension', cascade='all, delete-orphan')
    call_legs: Mapped[list['CallLeg']] = relationship('CallLeg', back_populates='extension')


# ─── Calls ────────────────────────────────────────────────────────────────────

class Call(Base):
    __tablename__ = 'calls'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    asterisk_unique_id: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    direction: Mapped[str] = mapped_column(String(10))         # inbound / outbound
    remote_number: Mapped[str] = mapped_column(String(30))
    contact_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration: Mapped[int] = mapped_column(Integer, default=0)  # seconds
    disposition: Mapped[str] = mapped_column(String(20), default='answered')
    recording_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recording_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    legs: Mapped[list['CallLeg']] = relationship('CallLeg', back_populates='call', cascade='all, delete-orphan')
    note: Mapped['CallNote | None'] = relationship('CallNote', back_populates='call', uselist=False, cascade='all, delete-orphan')

    __table_args__ = (
        Index('ix_calls_started_at', 'started_at'),
        Index('ix_calls_remote_number', 'remote_number'),
    )


class CallLeg(Base):
    """One call can have multiple legs (transfer, conference)."""
    __tablename__ = 'call_legs'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    call_id: Mapped[str] = mapped_column(String(36), ForeignKey('calls.id', ondelete='CASCADE'))
    extension_id: Mapped[str] = mapped_column(String(36), ForeignKey('voip_extensions.id'))
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    call: Mapped[Call] = relationship('Call', back_populates='legs')
    extension: Mapped[Extension] = relationship('Extension', back_populates='call_legs')


class CallNote(Base):
    __tablename__ = 'call_notes'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    call_id: Mapped[str] = mapped_column(String(36), ForeignKey('calls.id', ondelete='CASCADE'), unique=True)
    author_extension_id: Mapped[str] = mapped_column(String(36), ForeignKey('voip_extensions.id'))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    call: Mapped[Call] = relationship('Call', back_populates='note')


# ─── Voicemail ────────────────────────────────────────────────────────────────

class Voicemail(Base):
    __tablename__ = 'voicemails'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    caller_number: Mapped[str] = mapped_column(String(30))
    caller_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    duration: Mapped[int] = mapped_column(Integer, default=0)
    audio_path: Mapped[str] = mapped_column(String(500))
    audio_url: Mapped[str] = mapped_column(String(500))
    transcription: Mapped[str | None] = mapped_column(Text, nullable=True)
    listened: Mapped[bool] = mapped_column(Boolean, default=False)
    listened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extension_id: Mapped[str] = mapped_column(String(36), ForeignKey('voip_extensions.id'))
    deleted: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (Index('ix_voicemails_extension_listened', 'extension_id', 'listened'),)


# ─── SMS ──────────────────────────────────────────────────────────────────────

class SmsThread(Base):
    __tablename__ = 'sms_threads'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    external_number: Mapped[str] = mapped_column(String(30), index=True)
    contact_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_message_body: Mapped[str] = mapped_column(Text, default='')
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    assigned_to_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('voip_extensions.id'), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='open')   # open / archived
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    messages: Mapped[list['SmsMessage']] = relationship('SmsMessage', back_populates='thread', cascade='all, delete-orphan')
    assigned_to: Mapped[Extension | None] = relationship('Extension', foreign_keys=[assigned_to_id])

    __table_args__ = (Index('ix_sms_threads_status_updated', 'status', 'last_message_at'),)


class SmsMessage(Base):
    __tablename__ = 'sms_messages'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    thread_id: Mapped[str] = mapped_column(String(36), ForeignKey('sms_threads.id', ondelete='CASCADE'), index=True)
    direction: Mapped[str] = mapped_column(String(10))    # inbound / outbound
    body: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_by_id: Mapped[str | None] = mapped_column(String(36), ForeignKey('voip_extensions.id'), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default='sent')   # sending / sent / delivered / failed
    voipms_message_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    thread: Mapped[SmsThread] = relationship('SmsThread', back_populates='messages')
    sent_by: Mapped[Extension | None] = relationship('Extension', foreign_keys=[sent_by_id])


# ─── Push tokens ──────────────────────────────────────────────────────────────

class PushToken(Base):
    __tablename__ = 'push_tokens'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    extension_id: Mapped[str] = mapped_column(String(36), ForeignKey('voip_extensions.id', ondelete='CASCADE'), index=True)
    platform: Mapped[str] = mapped_column(String(10))    # ios / android
    token: Mapped[str] = mapped_column(String(500), unique=True)
    is_voip_push: Mapped[bool] = mapped_column(Boolean, default=False)   # PushKit vs APNs
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    extension: Mapped[Extension] = relationship('Extension', back_populates='push_tokens')


# ─── Routing rules ────────────────────────────────────────────────────────────

class RoutingRule(Base):
    __tablename__ = 'routing_rules'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    name: Mapped[str] = mapped_column(String(100))
    priority: Mapped[int] = mapped_column(Integer, default=10)
    schedule_type: Mapped[str] = mapped_column(String(20))   # business_hours / after_hours / lunch / holiday / manual
    destination_type: Mapped[str] = mapped_column(String(20))  # ring_all / extension / voicemail / ivr
    destination_value: Mapped[str] = mapped_column(String(100))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Audit log ────────────────────────────────────────────────────────────────

class VoipAuditLog(Base):
    """HIPAA-required audit trail for all VoIP access."""
    __tablename__ = 'voip_audit_logs'

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=gen_uuid)
    extension_id: Mapped[str] = mapped_column(String(36), index=True)
    action: Mapped[str] = mapped_column(String(50))
    resource_type: Mapped[str] = mapped_column(String(50))
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index('ix_audit_extension_created', 'extension_id', 'created_at'),)
