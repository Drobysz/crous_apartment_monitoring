from __future__ import annotations

from pathlib import Path

SUPPORTED_LANGUAGES = {"ru", "fr", "ar"}
LOCALES_DIR = Path(__file__).parents[1] / "locales"


def detect_language(language_code: str | None) -> str:
    candidate = (language_code or "").lower()
    return next((lang for lang in SUPPORTED_LANGUAGES if candidate.startswith(lang)), "fr")


class Translator:
    """Tiny Fluent-like loader for the project's intentionally simple key/value catalogs."""

    def __init__(self) -> None:
        self.catalogs = {lang: self._load(lang) for lang in SUPPORTED_LANGUAGES}

    def _load(self, language: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for line in (LOCALES_DIR / f"{language}.ftl").read_text(encoding="utf-8").splitlines():
            if " = " in line and not line.lstrip().startswith("#"):
                key, value = line.split(" = ", 1)
                result[key.strip()] = value
        return result

    def text(self, language: str, key: str, **variables: object) -> str:
        template = self.catalogs.get(language, self.catalogs["fr"]).get(key)
        if template is None:
            raise KeyError(f"Missing i18n key: {key}")
        return template.format(**variables)


i18n = Translator()
