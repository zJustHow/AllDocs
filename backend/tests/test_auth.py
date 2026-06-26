"""Auth API and RBAC tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.models import Base, Document, DocumentStatus, User, UserRole
from app.services.auth_service import AuthError, login_with_email, register_with_email, user_has_wechat


@pytest.fixture
async def auth_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.mark.asyncio
async def test_register_and_login_email(auth_db: AsyncSession) -> None:
    user, _, _ = await register_with_email(
        auth_db,
        email="user@example.com",
        password="password123",
    )
    await auth_db.commit()
    assert user.role == UserRole.user

    logged_in, access, refresh = await login_with_email(
        auth_db,
        email="user@example.com",
        password="password123",
    )
    await auth_db.commit()
    assert logged_in.id == user.id
    assert access
    assert refresh


@pytest.mark.asyncio
async def test_register_admin_role(auth_db: AsyncSession) -> None:
    user, _, _ = await register_with_email(
        auth_db,
        email="admin@example.com",
        password="password123",
        role=UserRole.admin,
    )
    assert user.role == UserRole.admin


@pytest.mark.asyncio
async def test_resolve_chat_doc_ids_for_regular_user(auth_db: AsyncSession) -> None:
    from app.services.auth_service import resolve_chat_doc_ids

    user, _, _ = await register_with_email(
        auth_db,
        email="reader@example.com",
        password="password123",
    )
    ready_id = uuid.uuid4()
    disabled_id = uuid.uuid4()
    pending_id = uuid.uuid4()
    auth_db.add_all(
        [
            Document(id=ready_id, name="a.pdf", object_key="a", status=DocumentStatus.ready),
            Document(
                id=disabled_id,
                name="c.pdf",
                object_key="c",
                status=DocumentStatus.ready,
                chat_enabled=False,
            ),
            Document(id=pending_id, name="b.pdf", object_key="b", status=DocumentStatus.pending),
        ]
    )
    await auth_db.flush()

    doc_ids = await resolve_chat_doc_ids(auth_db, user, [pending_id, disabled_id])
    assert doc_ids == [ready_id]


@pytest.mark.asyncio
async def test_resolve_chat_doc_ids_for_admin(auth_db: AsyncSession) -> None:
    from app.services.auth_service import resolve_chat_doc_ids

    admin = User(role=UserRole.admin, display_name="Admin")
    auth_db.add(admin)
    ready_id = uuid.uuid4()
    disabled_id = uuid.uuid4()
    auth_db.add_all(
        [
            Document(id=ready_id, name="a.pdf", object_key="a", status=DocumentStatus.ready),
            Document(
                id=disabled_id,
                name="b.pdf",
                object_key="b",
                status=DocumentStatus.ready,
                chat_enabled=False,
            ),
        ]
    )
    await auth_db.flush()
    doc_ids = await resolve_chat_doc_ids(auth_db, admin, [disabled_id])
    assert doc_ids == [ready_id]


@pytest.mark.asyncio
async def test_bind_phone_to_user(auth_db: AsyncSession) -> None:
    from app.services.auth_service import bind_phone_to_user, register_with_email

    user, _, _ = await register_with_email(
        auth_db,
        email="bind@test.com",
        password="password123",
    )
    await bind_phone_to_user(auth_db, user, "+8613900139000")
    await auth_db.commit()

    assert await user_has_wechat(auth_db, user.id) is False
    from app.services.auth_service import find_identity, IDENTITY_PHONE

    identity = await find_identity(auth_db, IDENTITY_PHONE, "+8613900139000")
    assert identity is not None
    assert identity.user_id == user.id


@pytest.mark.asyncio
async def test_bind_email_conflict(auth_db: AsyncSession) -> None:
    from app.services.auth_service import bind_email_to_user, register_with_email

    _user_a, _, _ = await register_with_email(
        auth_db,
        email="a@test.com",
        password="password123",
    )
    user_b, _, _ = await register_with_email(
        auth_db,
        email="b@test.com",
        password="password123",
    )
    with pytest.raises(AuthError) as exc:
        await bind_email_to_user(
            auth_db,
            user_b,
            email="a@test.com",
            password="password456",
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_normalize_phone(auth_db: AsyncSession) -> None:
    from app.services.auth_service import normalize_phone

    assert normalize_phone("13800138000") == "+8613800138000"
    assert normalize_phone("+8613800138000") == "+8613800138000"


@pytest.mark.asyncio
async def test_phone_otp_login(auth_db: AsyncSession) -> None:
    from app.services.otp_service import send_phone_otp, verify_phone_otp

    await send_phone_otp(auth_db, "13800138000")
    await auth_db.commit()

    # Code is logged in console provider; retrieve from latest challenge by brute force for test
    from sqlalchemy import select
    from app.db.models import OtpChallenge
    from app.services.sms_service import hash_otp_code

    # Instead, patch is cleaner - use known code path via hash
    result = await auth_db.execute(select(OtpChallenge))
    challenge = result.scalar_one()
    code = "123456"
    challenge.code_hash = hash_otp_code(code)
    await auth_db.flush()

    user, access, refresh = await verify_phone_otp(auth_db, "13800138000", code)
    await auth_db.commit()
    assert user.role == UserRole.user
    assert access
    assert refresh


@pytest.mark.asyncio
async def test_unbind_only_identity_fails(auth_db: AsyncSession) -> None:
    from app.services.auth_service import register_with_email, unbind_identity

    user, _, _ = await register_with_email(
        auth_db,
        email="solo@test.com",
        password="password123",
    )
    with pytest.raises(AuthError) as exc:
        await unbind_identity(auth_db, user, "email")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_unbind_email_when_phone_bound(auth_db: AsyncSession) -> None:
    from app.services.auth_service import bind_phone_to_user, register_with_email, unbind_identity

    user, _, _ = await register_with_email(
        auth_db,
        email="dual@test.com",
        password="password123",
    )
    await bind_phone_to_user(auth_db, user, "+8613800138000")
    await unbind_identity(auth_db, user, "email")
    await auth_db.commit()

    from app.services.auth_service import find_email_identity

    assert await find_email_identity(auth_db, "dual@test.com") is None


@pytest.mark.asyncio
async def test_admin_audit_log_on_user_update(auth_db: AsyncSession) -> None:
    from sqlalchemy import select

    from app.db.models import AdminAuditLog, User, UserRole
    from app.services.audit_service import record_admin_audit
    from app.services.auth_service import register_with_email

    admin, _, _ = await register_with_email(
        auth_db,
        email="admin@test.com",
        password="password123",
        role=UserRole.admin,
    )
    target = User(role=UserRole.user, display_name="Target")
    auth_db.add(target)
    await auth_db.flush()

    await record_admin_audit(
        auth_db,
        actor_user_id=admin.id,
        action="user.update",
        target_user_id=target.id,
        details={"role": {"from": "user", "to": "admin"}},
    )
    await auth_db.commit()

    result = await auth_db.execute(select(AdminAuditLog))
    log = result.scalar_one()
    assert log.action == "user.update"
    assert log.actor_user_id == admin.id
    assert log.target_user_id == target.id


@pytest.mark.asyncio
async def test_delete_document_writes_audit_log(auth_db: AsyncSession) -> None:
    from unittest.mock import patch

    from sqlalchemy import select

    from app.api.documents import delete_document
    from app.db.models import AdminAuditLog, Document, DocumentStatus, UserRole
    from app.services.auth_service import register_with_email

    admin, _, _ = await register_with_email(
        auth_db,
        email="admin@test.com",
        password="password123",
        role=UserRole.admin,
    )
    document = Document(
        name="manual.pdf",
        object_key="docs/manual.pdf",
        status=DocumentStatus.ready,
    )
    auth_db.add(document)
    await auth_db.flush()

    with patch("app.api.documents.enqueue"):
        result = await delete_document(document.id, auth_db, admin)

    assert result == {"status": "deleting"}
    logs = list((await auth_db.execute(select(AdminAuditLog))).scalars().all())
    assert len(logs) == 1
    assert logs[0].action == "document.delete"
    assert logs[0].actor_user_id == admin.id
    assert logs[0].details == {
        "document_id": str(document.id),
        "document_name": "manual.pdf",
    }


@pytest.mark.asyncio
async def test_set_document_chat_enabled_writes_audit_log(auth_db: AsyncSession) -> None:
    from app.api.documents import set_document_chat_enabled
    from app.api.schemas import DocumentChatEnabledRequest
    from sqlalchemy import select

    from app.db.models import AdminAuditLog, Document, DocumentStatus, UserRole
    from app.services.auth_service import register_with_email

    admin, _, _ = await register_with_email(
        auth_db,
        email="admin@test.com",
        password="password123",
        role=UserRole.admin,
    )
    document = Document(
        name="manual.pdf",
        object_key="docs/manual.pdf",
        status=DocumentStatus.ready,
        chat_enabled=False,
    )
    auth_db.add(document)
    await auth_db.flush()

    await set_document_chat_enabled(
        document.id,
        DocumentChatEnabledRequest(chat_enabled=True),
        auth_db,
        admin,
    )

    logs = list((await auth_db.execute(select(AdminAuditLog))).scalars().all())
    assert len(logs) == 1
    assert logs[0].action == "document.chat_enabled"
    assert logs[0].details["chat_enabled"] == {"from": False, "to": True}


def test_aliyun_rpc_signature() -> None:
    from app.services.aliyun_sms import sign_aliyun_rpc

    params = {
        "AccessKeyId": "test-key",
        "Action": "SendSms",
        "Format": "JSON",
        "PhoneNumbers": "8613800138000",
        "RegionId": "cn-hangzhou",
        "SignName": "Sign",
        "SignatureMethod": "HMAC-SHA1",
        "SignatureNonce": "nonce",
        "SignatureVersion": "1.0",
        "TemplateCode": "SMS_001",
        "TemplateParam": '{"code":"123456"}',
        "Timestamp": "2020-01-01T00:00:00Z",
        "Version": "2017-05-25",
    }
    signature = sign_aliyun_rpc(params, "test-secret")
    assert isinstance(signature, str)
    assert len(signature) > 0


@pytest.mark.asyncio
async def test_email_otp_register(auth_db: AsyncSession) -> None:
    from app.services.email_otp_service import send_register_email_otp, verify_register_email_otp
    from app.services.sms_service import hash_otp_code
    from sqlalchemy import select
    from app.db.models import OtpChallenge

    await send_register_email_otp(auth_db, "newuser@example.com")
    await auth_db.commit()

    result = await auth_db.execute(
        select(OtpChallenge).where(OtpChallenge.email == "newuser@example.com")
    )
    challenge = result.scalar_one()
    code = "654321"
    challenge.code_hash = hash_otp_code(code)
    await auth_db.flush()

    user, access, refresh = await verify_register_email_otp(
        auth_db,
        "newuser@example.com",
        code,
        password="password123",
        display_name="New User",
    )
    await auth_db.commit()
    assert user.display_name == "New User"
    assert access
    assert refresh


@pytest.mark.asyncio
async def test_email_otp_register_rejects_existing_email(auth_db: AsyncSession) -> None:
    from app.services.auth_service import register_with_email
    from app.services.email_otp_service import send_register_email_otp

    await register_with_email(
        auth_db,
        email="taken@example.com",
        password="password123",
    )
    with pytest.raises(AuthError) as exc:
        await send_register_email_otp(auth_db, "taken@example.com")
    assert exc.value.status_code == 409
