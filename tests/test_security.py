import unittest
from unittest.mock import Mock

from backend.auth import PERMISSIONS, permissions_for
from backend.models import Role, User
from backend.security import create_token, decode_token, hash_password, verify_password


class SecurityTests(unittest.TestCase):
    def test_password_hash(self):
        encoded = hash_password("safePassword123")
        self.assertTrue(verify_password("safePassword123", encoded))
        self.assertFalse(verify_password("wrong", encoded))

    def test_signed_token(self):
        token = create_token(42, "a-secret-long-enough-for-tests", 5)
        self.assertEqual(decode_token(token, "a-secret-long-enough-for-tests"), 42)
        with self.assertRaises(ValueError): decode_token(token, "wrong-secret")

    def test_admin_permissions_are_server_derived(self):
        role = Role(id=1, name="admin", permissions_json="[]")
        user = User(id=2, role_id=1)
        db = Mock(); db.get.return_value = role
        self.assertEqual(permissions_for(db, user), PERMISSIONS)


if __name__ == "__main__": unittest.main()
