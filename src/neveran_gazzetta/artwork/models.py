from __future__ import annotations

import base64
import binascii
import hashlib
from typing import Annotated, Literal
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic.alias_generators import to_camel

MAX_ARTWORK_BYTES = 6 * 1024 * 1024
MAX_ARTWORK_BASE64_CHARACTERS = ((MAX_ARTWORK_BYTES + 2) // 3) * 4


class ArtworkModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        alias_generator=to_camel,
    )


class ArtworkBrief(ArtworkModel):
    job_id: UUID
    issue_number: Annotated[int, Field(gt=0)]
    prompt: str = Field(min_length=80, max_length=6000)
    prompt_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    seed: Annotated[int, Field(ge=0, le=0xFFFF_FFFF)]
    alt: str = Field(min_length=1, max_length=320)
    caption: str = Field(min_length=1, max_length=320)
    credit: str = Field(min_length=1, max_length=160)
    focal_point: str = Field(pattern=r"^(?:100|\d{1,2})% (?:100|\d{1,2})%$")

    @model_validator(mode="after")
    def hash_prompt_coerente(self) -> ArtworkBrief:
        actual = hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()
        if actual != self.prompt_sha256:
            raise ValueError("prompt_sha256 non coincide con il prompt")
        return self


class GeneratedArtwork(ArtworkModel):
    src: str = Field(min_length=1, max_length=2048)
    object_key: str = Field(
        min_length=1,
        max_length=512,
        pattern=(
            r"^editions/issue-[0-9]{6,}-[0-9a-f-]+-lead-[a-f0-9]+"
            r"\.(?:png|jpg|webp)$"
        ),
    )
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model: str = Field(min_length=1, max_length=200)
    seed: Annotated[int, Field(ge=0, le=0xFFFF_FFFF)]
    width: Annotated[int, Field(ge=256, le=1920)]
    height: Annotated[int, Field(ge=256, le=1920)]
    cached: bool

    @model_validator(mode="after")
    def url_https(self) -> GeneratedArtwork:
        parsed = urlsplit(self.src)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("src artwork deve essere un URL HTTPS pubblico")
        return self


class WorkerGeneratedImage(ArtworkModel):
    image_base64: str = Field(
        min_length=16,
        max_length=MAX_ARTWORK_BASE64_CHARACTERS,
        repr=False,
    )
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    mime_type: Literal["image/png", "image/jpeg", "image/webp"]
    model: str = Field(min_length=1, max_length=200)
    seed: Annotated[int, Field(ge=0, le=0xFFFF_FFFF)]
    width: Annotated[int, Field(ge=256, le=1920)]
    height: Annotated[int, Field(ge=256, le=1920)]

    @model_validator(mode="after")
    def contenuto_coerente(self) -> WorkerGeneratedImage:
        self.decoded_bytes()
        return self

    def decoded_bytes(self) -> bytes:
        try:
            image = base64.b64decode(self.image_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("imageBase64 non valido") from exc
        if not image or len(image) > MAX_ARTWORK_BYTES:
            raise ValueError("Dimensione immagine non valida")
        detected = detect_image_mime(image)
        if detected != self.mime_type:
            raise ValueError("mimeType non coincide con il contenuto")
        digest = hashlib.sha256(image).hexdigest()
        if digest != self.content_sha256:
            raise ValueError("contentSha256 non coincide con il contenuto")
        return image


def detect_image_mime(image: bytes) -> Literal["image/png", "image/jpeg", "image/webp"]:
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(image) >= 12 and image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("Formato immagine non supportato")


def extension_for_mime(mime_type: str) -> str:
    return {
        "image/png": "png",
        "image/jpeg": "jpg",
        "image/webp": "webp",
    }[mime_type]
