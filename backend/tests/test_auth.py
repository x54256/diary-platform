"""Authentication lifetime and sliding-expiration tests."""

import unittest
from datetime import datetime, timezone

from fastapi import Response
from jose import jwt

from config import settings
from models.user import User
from services.auth import create_access_token, get_current_user


class _FakeQuery:
    def __init__(self, user: User):
        self.user = user

    def filter(self, *_args):
        return self

    def first(self):
        return self.user


class _FakeSession:
    def __init__(self, user: User):
        self.user = user

    def query(self, _model):
        return _FakeQuery(self.user)


class AuthenticationTest(unittest.TestCase):
    def test_access_token_is_valid_for_30_days(self):
        before = datetime.now(timezone.utc).timestamp()

        token = create_access_token({"sub": "alice"})

        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        lifetime = payload["exp"] - before
        self.assertGreaterEqual(lifetime, 30 * 24 * 60 * 60 - 2)
        self.assertLessEqual(lifetime, 30 * 24 * 60 * 60 + 2)

    def test_authenticated_request_returns_renewed_token(self):
        user = User(username="alice", password_encrypted="encrypted")
        response = Response()

        current_user = get_current_user(
            response=response,
            token=create_access_token({"sub": "alice"}),
            db=_FakeSession(user),
        )

        renewed_token = response.headers["X-Access-Token"]
        payload = jwt.decode(renewed_token, settings.SECRET_KEY, algorithms=["HS256"])
        self.assertIs(current_user, user)
        self.assertEqual(payload["sub"], "alice")


if __name__ == "__main__":
    unittest.main()
