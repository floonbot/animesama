import os
from urllib.parse import urlparse

SITE_URL = os.getenv("SITE_URL", "https://anime-sama.to").strip().rstrip("/")
SITE_DOMAIN = os.getenv("SITE_DOMAIN", "").strip().lower() or (urlparse(SITE_URL).hostname or "anime-sama.to")

COVERS_BASE = os.getenv(
    "COVERS_BASE", "https://raw.githubusercontent.com/Anime-Sama/IMG/img/contenu"
).rstrip("/")

LOGIN_URL = f"{SITE_URL}/login"

LOGIN_API = f"{SITE_URL}/api/auth/login.php"
GETDATA_API = f"{SITE_URL}/api/get-data.php"

SEARCH_URL = f"{SITE_URL}/template-php/defaut/fetch.php"

SCAN_API_CHAP = f"{SITE_URL}/s2/scans/get_nb_chap_et_img.php"
SCAN_LANGS = ("vf", "va")

SITE_LANGS = (
    "vostfr", "vf1", "vf2", "vf", "var", "va",
    "vkr", "vcn", "vqc", "vj",
)
