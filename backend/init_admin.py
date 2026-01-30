import sys
import uuid
from datetime import datetime, timezone

from passlib.context import CryptContext

from database import db

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def init_admin():
    print("🔍 Проверка существующих администраторов...")
    
    print("\n📝 Создание главного администратора")
    print("=" * 50)

    email = input("Email администратора: ").strip()

    if not email:
        print("❌ Email не может быть пустым")
        return

    existing_user = db.get_user_by_email(email)
    if existing_user:
        print(f"❌ Пользователь с email {email} уже существует")
        return

    password = input("Пароль (оставьте пустым для автогенерации): ").strip()

    if not password:
        import secrets
        password = secrets.token_urlsafe(12)
        print(f"🔑 Сгенерирован пароль: {password}")

    hashed_password = pwd_context.hash(password)

    admin_user = {
        "id": str(uuid.uuid4()),
        "email": email,
        "password": hashed_password,
        "role": "admin",
        "is_superadmin": True,
        "can_delete_without_approval": True,
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    db.create_user(admin_user)

    print("\n✅ Администратор успешно создан!")
    print("=" * 50)
    print(f"📧 Email: {email}")
    print(f"🔑 Пароль: {password}")
    print("=" * 50)
    print("\n⚠️  ВАЖНО: Сохраните эти данные в безопасном месте!")


if __name__ == "__main__":
    try:
        init_admin()
    except KeyboardInterrupt:
        print("\n\n❌ Прервано пользователем")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        sys.exit(1)