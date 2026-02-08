"""EVE Online SSO OAuth2 PKCE authentication."""

import base64
import hashlib
import logging
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx
import jwt
from cryptography.fernet import Fernet

from .models import ESIConfig, ESIToken

logger = logging.getLogger(__name__)

# EVE SSO endpoints
AUTH_BASE = "https://login.eveonline.com"
AUTH_URL = f"{AUTH_BASE}/v2/oauth/authorize"
TOKEN_URL = f"{AUTH_BASE}/v2/oauth/token"
JWKS_URL = f"{AUTH_BASE}/oauth/jwks"
ISSUER = AUTH_BASE

# JWKS cache
_jwks_cache: dict | None = None
_jwks_cache_time: float = 0
JWKS_CACHE_TTL = 3600  # 1 hour


class ESIAuth:
    """Handles EVE SSO OAuth2 PKCE flow for native/desktop apps."""

    def __init__(self, config: ESIConfig, encryption_key: bytes):
        self.config = config
        self._fernet = Fernet(encryption_key)
        self._client = httpx.AsyncClient()
        self._pending_states: dict[str, str] = {}  # state -> code_verifier

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    def get_authorization_url(self) -> tuple[str, str]:
        """
        Generate OAuth2 authorization URL with PKCE.

        Returns:
            Tuple of (authorization_url, state)
        """
        # Generate PKCE code verifier and challenge
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=").decode()

        state = secrets.token_urlsafe(32)

        # Store verifier for later exchange
        self._pending_states[state] = code_verifier

        callback_url = f"http://localhost:{self.config.callback_port}{self.config.callback_path}"
        scopes = " ".join(self.config.scopes)

        params = {
            "response_type": "code",
            "redirect_uri": callback_url,
            "client_id": self.config.client_id,
            "scope": scopes,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }

        auth_url = f"{AUTH_URL}?{urlencode(params)}"

        logger.info("Generated authorization URL with state=%s", state[:8])
        return auth_url, state

    async def exchange_code(self, code: str, state: str) -> ESIToken:
        """
        Exchange authorization code for tokens using PKCE.

        Args:
            code: Authorization code from callback
            state: State parameter from callback

        Returns:
            ESIToken with character info and tokens

        Raises:
            ValueError: If state is invalid or token exchange fails
        """
        code_verifier = self._pending_states.pop(state, None)
        if code_verifier is None:
            raise ValueError("Invalid or expired state parameter")

        callback_url = f"http://localhost:{self.config.callback_port}{self.config.callback_path}"

        response = await self._client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self.config.client_id,
                "code_verifier": code_verifier,
                "redirect_uri": callback_url,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if response.status_code != 200:
            logger.error("Token exchange failed: %s %s", response.status_code, response.text)
            raise ValueError(f"Token exchange failed: {response.status_code}")

        data = response.json()

        # Validate the JWT access token
        claims = await self._validate_jwt(data["access_token"])

        # Extract character info from sub claim: "CHARACTER:EVE:<id>"
        sub = claims.get("sub", "")
        parts = sub.split(":")
        if len(parts) != 3 or parts[0] != "CHARACTER" or parts[1] != "EVE":
            raise ValueError(f"Unexpected sub claim format: {sub}")

        character_id = int(parts[2])
        character_name = claims.get("name", "Unknown")

        expires_at = datetime.now() + timedelta(seconds=data["expires_in"])
        scopes = data.get("scope", "").split() if data.get("scope") else []

        token = ESIToken(
            character_id=character_id,
            character_name=character_name,
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=expires_at,
            scopes=scopes,
        )

        logger.info(
            "Authenticated character: %s (ID: %d)", character_name, character_id
        )
        return token

    async def refresh_token(self, token: ESIToken) -> ESIToken:
        """
        Refresh an expired token.

        Args:
            token: Token with valid refresh_token

        Returns:
            New ESIToken with fresh access_token and updated refresh_token
        """
        response = await self._client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": token.refresh_token,
                "client_id": self.config.client_id,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )

        if response.status_code != 200:
            logger.error("Token refresh failed: %s %s", response.status_code, response.text)
            raise ValueError(f"Token refresh failed: {response.status_code}")

        data = response.json()

        expires_at = datetime.now() + timedelta(seconds=data["expires_in"])
        scopes = data.get("scope", "").split() if data.get("scope") else token.scopes

        refreshed = ESIToken(
            character_id=token.character_id,
            character_name=token.character_name,
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token", token.refresh_token),
            expires_at=expires_at,
            scopes=scopes,
        )

        logger.debug("Refreshed token for character %d", token.character_id)
        return refreshed

    async def _validate_jwt(self, access_token: str) -> dict:
        """
        Validate an EVE SSO JWT access token.

        Args:
            access_token: JWT to validate

        Returns:
            Decoded JWT claims
        """
        global _jwks_cache, _jwks_cache_time

        # Fetch or use cached JWKS
        if _jwks_cache is None or (time.time() - _jwks_cache_time) > JWKS_CACHE_TTL:
            response = await self._client.get(JWKS_URL)
            response.raise_for_status()
            _jwks_cache = response.json()
            _jwks_cache_time = time.time()
            logger.debug("Fetched JWKS from %s", JWKS_URL)

        # Get the signing key
        jwks_client = jwt.PyJWKSet.from_dict(_jwks_cache)

        # Decode header to find kid
        header = jwt.get_unverified_header(access_token)
        kid = header.get("kid")

        signing_key = None
        for key in jwks_client.keys:
            if key.key_id == kid:
                signing_key = key
                break

        if signing_key is None:
            raise ValueError(f"No matching JWK found for kid={kid}")

        claims = jwt.decode(
            access_token,
            signing_key,
            algorithms=["RS256"],
            issuer=ISSUER,
            options={"verify_aud": False},
        )

        return claims

    def encrypt_refresh_token(self, token: str) -> str:
        """Encrypt a refresh token for database storage."""
        return self._fernet.encrypt(token.encode()).decode()

    def decrypt_refresh_token(self, encrypted: str) -> str:
        """Decrypt a refresh token from database storage."""
        return self._fernet.decrypt(encrypted.encode()).decode()
