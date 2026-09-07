import base64
import unittest
from urllib.error import URLError
from backend.ttlock_client import (
    TTLockClient, SecretBox, LockError, OutcomeUnknown, https_required,
)


class TTLockBoundaryTests(unittest.TestCase):
    def test_disabled_without_explicit_real_opt_in(self):
        with self.assertRaises(LockError):
            TTLockClient("cn", "app")
        with self.assertRaises(LockError):
            TTLockClient("https://attacker.invalid", "app", transport=lambda *a: {})

    def test_encryption_is_random_authenticated_and_tenant_bound(self):
        box = SecretBox(base64.b64encode(b"x" * 32).decode())
        first = box.encrypt("sensitive", "store:1:credential")
        second = box.encrypt("sensitive", "store:1:credential")
        self.assertNotEqual(first, second)
        self.assertNotIn("sensitive", first)
        self.assertEqual(box.decrypt(first, "store:1:credential"), "sensitive")
        with self.assertRaises(LockError):
            box.decrypt(first, "store:2:credential")
        with self.assertRaises(LockError):
            box.decrypt(first[:-4] + "AAAA", "store:1:credential")
        with self.assertRaises(LockError):
            SecretBox("not a key")

    def test_production_rejects_plaintext(self):
        with self.assertRaises(LockError):
            https_required("http", production=True)
        https_required("https", production=True)

    def test_auth_and_refresh_wire_shape(self):
        calls = []
        def transport(url, payload, timeout):
            calls.append((url, payload, timeout))
            return {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}
        client = TTLockClient("cn", "app", transport=transport, clock=lambda: 1000)
        tokens = client.authorize("secret", "account", "password")
        self.assertEqual(tokens.expires_at, 4600)
        self.assertNotIn("access", repr(tokens))
        self.assertEqual(calls[0][1]["password"], "5f4dcc3b5aa765d61d8327deb882cf99")
        client.refresh("secret", tokens.refresh_token)
        self.assertEqual(calls[-1][1]["grant_type"], "refresh_token")
        self.assertEqual(calls[-1][1]["client_secret"], "secret")

    def test_creation_is_once_and_timeout_is_unknown(self):
        calls = []
        def transport(url, payload, timeout):
            calls.append(payload)
            raise URLError("secret-response")
        client = TTLockClient("cn", "app", transport=transport)
        with self.assertRaises(OutcomeUnknown) as error:
            client.one_time("token", 1, 4, "request-unique", start_ms=0)
        self.assertEqual(len(calls), 1)
        self.assertNotIn("secret", str(error.exception))
        self.assertEqual(calls[0]["keyboardPwdType"], 1)

    def test_invalid_success_payload_is_unknown(self):
        client = TTLockClient("cn", "app", transport=lambda *args: {})
        with self.assertRaises(OutcomeUnknown):
            client.one_time("token", 1, 4, "request", start_ms=0)
        with self.assertRaises(LockError):
            client.one_time("token", 1, 3, "request", start_ms=0)

    def test_password_result_has_no_secret_repr(self):
        client = TTLockClient("cn", "app", transport=lambda *args:
            {"keyboardPwd": "12345678", "keyboardPwdId": 10})
        result = client.one_time("token", 1, 4, "request", start_ms=0)
        self.assertEqual(result.end_ms, 21600000)
        self.assertNotIn("12345678", repr(result))

    def test_no_match_does_not_mean_safe_to_reissue(self):
        client = TTLockClient("cn", "app", transport=lambda *args: {"list": []})
        with self.assertRaises(OutcomeUnknown):
            client.find_created("token", 1, "request")

    def test_lock_list_does_not_expose_lock_data(self):
        client = TTLockClient("cn", "app", transport=lambda *args:
            {"list": [{"lockId": 1, "lockAlias": "大门", "keyboardPwdVersion": 4, "lockData": "SECRET"}]})
        self.assertNotIn("SECRET", str(client.locks("token")))

    def test_unique_reconciliation(self):
        client = TTLockClient("cn", "app", transport=lambda *args:
            {"list": [{"keyboardPwdName": "request", "keyboardPwdType": 1,
                       "keyboardPwdId": 7, "keyboardPwd": "123456", "startDate": 0, "endDate": 21600000}]})
        self.assertEqual(client.find_created("token", 1, "request").remote_id, "7")


if __name__ == "__main__":
    unittest.main()
