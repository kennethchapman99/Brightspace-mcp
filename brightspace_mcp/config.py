"""
Configuration helpers for the Brightspace MCP server.

This module uses pydantic to model and validate the environment variables
required to connect to Brightspace (Valence) APIs.  The values are
loaded from `.env` using python‑dotenv when the module is imported.

Attributes:
    Settings: A pydantic model encapsulating the required and optional
      configuration values.
    load_settings(): Returns a configured Settings instance using the
      environment.
"""

from __future__ import annotations

import os
from pydantic import BaseModel, Field, HttpUrl
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env, if present


class Settings(BaseModel):
    """Pydantic model containing configuration for Brightspace APIs."""

    base_url: HttpUrl = Field(..., description="Base URL of your Brightspace instance, e.g. https://your.brightspace.host")
    client_id: str = Field(..., description="OAuth2 client ID from your Brightspace application")
    client_secret: str = Field(..., description="OAuth2 client secret from your Brightspace application")
    refresh_token: str = Field(..., description="Long-lived OAuth2 refresh token")
    # Version numbers may be overridden by environment variables.  These values are
    # used for convenience wrappers in brightspace.py.  If endpoints change,
    # update these or supply explicit paths when calling the generic `bs.request` tool.
    lp_ver: str = Field(default_factory=lambda: os.getenv("BS_LP_VERSION", "1.46"), description="Learning Platform API version")
    le_ver: str = Field(default_factory=lambda: os.getenv("BS_LE_VERSION", "1.74"), description="Learning Environment API version")
    ver: str = Field(default_factory=lambda: os.getenv("BS_DEFAULT_VERSION", "1.46"), description="Default API version for generic requests")


def load_settings() -> Settings:
    """Load configuration from environment variables and return Settings instance."""
    return Settings(
        base_url=os.getenv("BS_BASE_URL"),
        client_id=os.getenv("BS_CLIENT_ID"),
        client_secret=os.getenv("BS_CLIENT_SECRET"),
        refresh_token=os.getenv("BS_REFRESH_TOKEN"),
    )