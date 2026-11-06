"""
Localization catalog for nautilus-compact-list.

Provides concise, native translations for extension-specific strings
without requiring external .mo/.po gettext compilation or system installation.
"""

import os


TRANSLATIONS = {
    # French — No verb for brevity
    "fr": {
        "Set Max Column Width…": "Largeur max. des colonnes…",
        "Max chars:": "Caractères max. :",
        "Apply": "Appliquer",
    },
    # German
    "de": {
        "Set Max Column Width…": "Max. Spaltenbreite festlegen…",
        "Max chars:": "Max. Zeichen:",
        "Apply": "Anwenden",
    },
    # Spanish — No verb for brevity
    "es": {
        "Set Max Column Width…": "Ancho máx. de columnas…",
        "Max chars:": "Máx. de caracteres:",
        "Apply": "Aplicar",
    },
    # Italian — No verb for brevity
    "it": {
        "Set Max Column Width…": "Larghezza max. colonne…",
        "Max chars:": "Max. caratteri:",
        "Apply": "Applica",
    },
    # Portuguese — No verb for brevity
    "pt": {
        "Set Max Column Width…": "Largura máx. das colunas…",
        "Max chars:": "Máx. de caracteres:",
        "Apply": "Aplicar",
    },
    # Russian — Short infinitive "Задать"
    "ru": {
        "Set Max Column Width…": "Задать макс. ширину колонок…",
        "Max chars:": "Макс. символов:",
        "Apply": "Применить",
    },
    # Polish — Imperative "Ustaw"
    "pl": {
        "Set Max Column Width…": "Ustaw maks. szerokość kolumn…",
        "Max chars:": "Maks. znaków:",
        "Apply": "Zastosuj",
    },
    # Dutch
    "nl": {
        "Set Max Column Width…": "Max. kolombreedte instellen…",
        "Max chars:": "Max. tekens:",
        "Apply": "Toepassen",
    },
    # Swedish — Imperative "Ange" + "max" without period
    "sv": {
        "Set Max Column Width…": "Ange max kolumnbredd…",
        "Max chars:": "Max antal tecken:",
        "Apply": "Verkställ",
    },
    # Norwegian Bokmål — Imperative "Angi" + "maks." with period
    "nb": {
        "Set Max Column Width…": "Angi maks. kolonnebredde…",
        "Max chars:": "Maks. tegn:",
        "Apply": "Bruk",
    },
    # Norwegian Nynorsk — Imperative "Set" + "maks." with period
    "nn": {
        "Set Max Column Width…": "Set maks. kolonnebreidd…",
        "Max chars:": "Maks. teikn:",
        "Apply": "Bruk",
    },
    # Danish — Imperative "Angiv" + "maks."
    "da": {
        "Set Max Column Width…": "Angiv maks. kolonnebredde…",
        "Max chars:": "Maks. tegn:",
        "Apply": "Anvend",
    },
    # Finnish — compound nouns are preferred over abbreviations
    "fi": {
        "Set Max Column Width…": "Sarakkeen enimmäisleveys…",
        "Max chars:": "Merkkejä enintään:",
        "Apply": "Käytä",
    },
    # Czech — No verb for brevity
    "cs": {
        "Set Max Column Width…": "Max. šířka sloupců…",
        "Max chars:": "Max. znaků:",
        "Apply": "Použít",
    },
    # Hungarian — No verb for brevity
    "hu": {
        "Set Max Column Width…": "Max. oszlopszélesség…",
        "Max chars:": "Max. karakter:",
        "Apply": "Alkalmaz",
    },
    # Turkish — sentence case is standard in Turkish GNOME UI
    "tr": {
        "Set Max Column Width…": "Maks. sütun genişliği…",
        "Max chars:": "Maks. karakter:",
        "Apply": "Uygula",
    },
    # Romanian — No verb for brevity
    "ro": {
        "Set Max Column Width…": "Lățimea max. a coloanelor…",
        "Max chars:": "Nr. max. caractere:",
        "Apply": "Aplică",
    },
    # Greek — Verbal noun "Ορισμός"
    "el": {
        "Set Max Column Width…": "Ορισμός μέγ. πλάτους στηλών…",
        "Max chars:": "Μέγ. χαρακτήρες:",
        "Apply": "Εφαρμογή",
    },
    # Ukrainian — Short infinitive "Задати"
    "uk": {
        "Set Max Column Width…": "Задати макс. ширину колонок…",
        "Max chars:": "Макс. символів:",
        "Apply": "Застосувати",
    },
    # Japanese — Verb "設定" at the end
    "ja": {
        "Set Max Column Width…": "列の最大幅を設定…",
        "Max chars:": "最大文字数:",
        "Apply": "適用",
    },
    # Simplified Chinese — Verb "设置" at the start
    "zh_cn": {
        "Set Max Column Width…": "设置最大列宽…",
        "Max chars:": "最大字符数：",
        "Apply": "应用",
    },
    # Traditional Chinese — Verb "設定" at the start
    "zh_tw": {
        "Set Max Column Width…": "設定最大欄寬…",
        "Max chars:": "最大字元數：",
        "Apply": "套用",
    },
    # Korean — Verbal noun "설정" at the end
    "ko": {
        "Set Max Column Width…": "최대 열 너비 설정…",
        "Max chars:": "최대 글자 수:",
        "Apply": "적용",
    },
    # Arabic — Verbal noun "تعيين" at the start
    "ar": {
        "Set Max Column Width…": "تعيين أقصى عرض للعمود…",
        "Max chars:": "أقصى عدد للأحرف:",
        "Apply": "تطبيق",
    },
    # Hebrew — Verbal noun "הגדרת" at the start
    "he": {
        "Set Max Column Width…": "הגדרת רוחב עמודה מרבי…",
        "Max chars:": "מס׳ תווים מרבי:",
        "Apply": "החלה",
    },
    # Indonesian — Imperative "Atur" in sentence case
    "id": {
        "Set Max Column Width…": "Atur lebar kolom maks.…",
        "Max chars:": "Maks. karakter:",
        "Apply": "Terapkan",
    },
    # Catalan — No verb for brevity
    "ca": {
        "Set Max Column Width…": "Amplada màx. de columnes…",
        "Max chars:": "Màx. de caràcters:",
        "Apply": "Aplica",
    },
    # Hindi — Verb "सेट करें" at the end
    "hi": {
        "Set Max Column Width…": "अधिकतम स्तंभ चौड़ाई सेट करें…",
        "Max chars:": "अधिकतम वर्ण:",
        "Apply": "लागू करें",
    },
}


def _t(msg: str) -> str:
    """
    Translates `msg` into the active desktop language.
    Checks full locale (e.g. 'zh_cn', 'zh_tw') first, then language prefix ('fr', 'de', 'pt').
    English variants ('en_us', 'en_gb', 'en_ca', etc.) directly return English `msg`.
    Falls back to English `msg` if no translation is found.
    """
    raw = (
        os.environ.get("LANGUAGE")
        or os.environ.get("LC_ALL")
        or os.environ.get("LC_MESSAGES")
        or os.environ.get("LANG")
        or ""
    )
    # Extract clean locale tag, e.g. "fr_FR.UTF-8" -> "fr_fr", "fr"
    clean = raw.split(":")[0].split(".")[0].strip().lower()
    lang_code = clean.split("_")[0]
    if lang_code == "en":
        return msg

    if clean in TRANSLATIONS and msg in TRANSLATIONS[clean]:
        return TRANSLATIONS[clean][msg]

    if lang_code in TRANSLATIONS and msg in TRANSLATIONS[lang_code]:
        return TRANSLATIONS[lang_code][msg]

    return msg