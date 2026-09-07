"""通通锁请求适配层，默认禁止真实调用。

不依赖数据库，不记录上游请求和响应正文。各项目使用独立模块与加密密钥。
"""
import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler

from Crypto.Cipher import AES


REGIONS = {"cn": "https://api.sciener.com", "eu": "https://euapi.ttlock.com"}


class LockError(Exception):
    """可展示给用户的错误，不包含上游响应正文。"""


class OutcomeUnknown(LockError):
    """请求可能已经到达通通锁，必须先核对，不能盲目重发。"""


class ReauthorizationRequired(LockError):
    pass


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def https_required(scheme, *, production):
    # 是否信任代理由服务器配置决定，不能直接相信客户端请求头。
    if production and scheme != "https":
        raise LockError("门锁授权和密码操作必须通过 HTTPS 访问")


class SecretBox:
    """使用AES-256-GCM加密，并绑定门店及用途，防止跨门店替换密文。"""
    def __init__(self, encoded_key):
        try:
            self.key = base64.b64decode(encoded_key, validate=True)
        except Exception:
            raise LockError("门锁加密主密钥格式不正确") from None
        if len(self.key) != 32:
            raise LockError("门锁加密主密钥必须为32字节的Base64编码")

    def encrypt(self, plaintext, context):
        nonce = secrets.token_bytes(12)
        cipher = AES.new(self.key, AES.MODE_GCM, nonce=nonce)
        cipher.update(context.encode("utf-8"))
        ciphertext, tag = cipher.encrypt_and_digest(plaintext.encode("utf-8"))
        return "v1:" + base64.b64encode(nonce + tag + ciphertext).decode("ascii")

    def decrypt(self, envelope, context):
        try:
            if not envelope.startswith("v1:"):
                raise ValueError()
            raw = base64.b64decode(envelope[3:], validate=True)
            cipher = AES.new(self.key, AES.MODE_GCM, nonce=raw[:12])
            cipher.update(context.encode("utf-8"))
            return cipher.decrypt_and_verify(raw[28:], raw[12:28]).decode("utf-8")
        except Exception:
            raise LockError("门锁密文无法验证，请检查加密主密钥") from None


@dataclass(frozen=True, repr=False)
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: int

    @classmethod
    def parse(cls, data, now):
        try:
            access = data["access_token"]
            refresh = data["refresh_token"]
            lifetime = int(data["expires_in"])
            if not isinstance(access, str) or not access or not isinstance(refresh, str) or not refresh or lifetime <= 0:
                raise ValueError()
            return cls(access, refresh, now + lifetime)
        except (KeyError, TypeError, ValueError):
            raise ReauthorizationRequired("通通锁授权响应无效，请重新授权") from None


@dataclass(frozen=True, repr=False)
class Passcode:
    remote_id: str
    password: str
    start_ms: int
    end_ms: int


def http_post(url, data, timeout):
    req = Request(url, data=urlencode(data).encode("utf-8"), method="POST",
                  headers={"Content-Type": "application/x-www-form-urlencoded"})
    # 禁止重定向，防止凭证被转发到其他主机。
    with build_opener(_NoRedirect()).open(req, timeout=timeout) as response:
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError("oversized response")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError("invalid response")
        return result


class TTLockClient:
    def __init__(self, region, client_id, *, transport=None, real_enabled=False, clock=time.time):
        if region not in REGIONS:
            raise LockError("不支持的通通锁服务区域")
        if transport is None and not real_enabled:
            raise LockError("真实门锁调用尚未启用")
        self.base = REGIONS[region]
        self.client_id = client_id
        self.transport = transport or http_post
        self.clock = clock

    def _post(self, path, payload, *, creates_password=False):
        try:
            data = self.transport(self.base + path, payload, 10)
            if not isinstance(data, dict):
                raise ValueError()
        except (HTTPError, URLError, TimeoutError, OSError, ValueError):
            if creates_password:
                raise OutcomeUnknown("正在确认发码结果，请勿重复创建") from None
            raise LockError("通通锁暂时无法连接，请稍后重试") from None
        if data.get("errcode") not in (None, 0, "0"):
            # 不回显上游错误原文，其中可能包含账号或凭证。
            raise LockError("通通锁拒绝了请求，请检查授权及门锁权限")
        return data

    def authorize(self, secret, username, password):
        data = self._post("/oauth2/token", {
            "client_id": self.client_id, "client_secret": secret,
            "username": username,
            # MD5仅用于满足通通锁接口协议，不用于本地密码存储。
            "password": hashlib.md5(password.encode("utf-8")).hexdigest(),
        })
        return Tokens.parse(data, int(self.clock()))

    def refresh(self, secret, refresh_token):
        data = self._post("/oauth2/token", {
            "client_id": self.client_id, "client_secret": secret,
            "grant_type": "refresh_token", "refresh_token": refresh_token,
        })
        return Tokens.parse(data, int(self.clock()))

    def _api(self, path, token, values, *, creates_password=False):
        return self._post(path, dict(values, clientId=self.client_id,
            accessToken=token, date=int(self.clock() * 1000)),
            creates_password=creates_password)

    def locks(self, token, page=1):
        data = self._api("/v3/lock/list", token, {"pageNo": page, "pageSize": 100})
        rows = data.get("list")
        if not isinstance(rows, list):
            raise LockError("通通锁门锁列表响应无效")
        # 只返回选锁所需字段，不暴露门锁操作数据等敏感内容。
        return [{"lock_id": x["lockId"], "name": x.get("lockAlias") or x.get("lockName", ""),
                 "password_version": x.get("keyboardPwdVersion")} for x in rows]

    def one_time(self, token, lock_id, version, request_name, *, start_ms):
        if version != 4:
            raise LockError("第一版仅支持已验证的第四版密码门锁")
        if not request_name or len(request_name) > 64:
            raise LockError("发码请求标识无效")
        if start_ms % 3_600_000:
            raise LockError("密码生效时间必须对齐整点")
        data = self._api("/v3/keyboardPwd/get", token, {
            "lockId": lock_id, "keyboardPwdVersion": version,
            "keyboardPwdType": 1, "keyboardPwdName": request_name,
            "startDate": start_ms, "endDate": start_ms + 21_600_000,
        }, creates_password=True)
        try:
            password = data["keyboardPwd"]
            remote_id = str(data["keyboardPwdId"])
            if not isinstance(password, str) or not password.isascii() or not password.isdigit() or not remote_id:
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise OutcomeUnknown("发码响应不完整，正在确认结果，请勿重复创建") from None
        return Passcode(remote_id, password, start_ms, start_ms + 21_600_000)

    def find_created(self, token, lock_id, request_name, *, max_pages=100):
        """通过持久化的唯一请求名称核对；没查到记录不代表发码失败。"""
        matches = []
        for page in range(1, max_pages + 1):
            data = self._api("/v3/lock/listKeyboardPwd", token,
                {"lockId": lock_id, "pageNo": page, "pageSize": 100})
            rows = data.get("list")
            if not isinstance(rows, list):
                raise OutcomeUnknown("暂时无法核对发码结果，请联系店长")
            matches.extend(x for x in rows if x.get("keyboardPwdName") == request_name
                           and x.get("keyboardPwdType") == 1)
            if len(rows) < 100:
                break
        else:
            raise OutcomeUnknown("密码记录过多，发码结果需要人工核对")
        if len(matches) != 1:
            raise OutcomeUnknown("尚不能唯一确认发码结果，请联系店长，勿重复创建")
        row = matches[0]
        try:
            code = str(row["keyboardPwd"])
            if not code.isascii() or not code.isdigit():
                raise ValueError()
            return Passcode(str(row["keyboardPwdId"]), code,
                            int(row["startDate"]), int(row["endDate"]))
        except (KeyError, ValueError, TypeError):
            raise OutcomeUnknown("密码记录不完整，发码结果需要人工核对") from None
