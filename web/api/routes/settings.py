import asyncio
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Query
from pydantic import BaseModel

from engine.config.user_settings import (
    QUALITES_VALIDES,
    load_settings,
    save_settings,
)

router = APIRouter()
log    = logging.getLogger("web.api.settings")

class SettingsBody(BaseModel):
    qualite:       str | None  = None
    thread_count:  int | None  = None
    downloads_dir: str | None  = None
    scans_dir:     str | None  = None
    notifications: bool | None = None
    son_notif:      bool | None = None
    confirm_suppr:  bool | None = None
    skip_existants: bool | None = None
    langue_defaut:  str  | None = None

def _valider_dossier(chemin: str) -> tuple[bool, str]:
    if chemin == "":
        return True, ""
    try:
        p = Path(chemin).expanduser()
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            log.info(f"Dossier créé : {p}")
        if not p.is_dir():
            return False, f"Ce n'est pas un dossier : {chemin}"
        if not os.access(p, os.W_OK):
            return False, f"Dossier non accessible en écriture : {chemin}"
        return True, str(p)
    except OSError as e:
        return False, f"Impossible de créer/accéder au dossier : {e}"
    except ValueError:
        return False, "Chemin invalide"

# pathlib avale l'erreur : Path("a\x00b").exists() rend False au lieu de lever,
# et la sonde annoncait « sera cree » pour un chemin que mkdir refuserait.
_CAR_INTERDITS_NT = set('<>:"|?*')

def _caractere_interdit(p: Path) -> str:
    _, reste = os.path.splitdrive(str(p))
    for ch in reste:
        if ch == "\x00" or ord(ch) < 32:
            return "caractère de contrôle"
        if os.name == "nt" and ch in _CAR_INTERDITS_NT:
            return f"« {ch} »"
    return ""

# _valider_dossier cree le dossier absent : une faute de frappe fabriquait un
# dossier fantome en silence. Cette sonde repond la meme chose sans rien ecrire,
# pour que l'interface puisse demander confirmation avant d'en arriver la.
def _sonder_dossier(chemin: str) -> dict:
    brut = (chemin or "").strip()
    if not brut:
        return {
            "ok": True, "defaut": True, "existe": False, "creable": False,
            "inscriptible": False, "chemin": "",
            "message": "Dossier par défaut de l'application",
        }

    reponse = {"ok": False, "defaut": False, "existe": False, "creable": False,
               "inscriptible": False, "chemin": brut, "message": ""}
    try:
        p = Path(brut).expanduser()
        reponse["chemin"] = str(p)
        interdit = _caractere_interdit(p)
        if interdit:
            reponse["message"] = f"Caractère interdit dans un chemin : {interdit}"
            return reponse
        if p.exists():
            reponse["existe"] = True
            if not p.is_dir():
                reponse["message"] = f"Ce n'est pas un dossier : {p}"
                return reponse
            if not os.access(p, os.W_OK):
                reponse["message"] = f"Dossier non accessible en écriture : {p}"
                return reponse
            reponse["ok"] = True
            reponse["inscriptible"] = True
            reponse["message"] = f"Dossier existant : {p}"
            return reponse

        # Un lecteur absent n'est pas un dossier « a creer » : rien ne peut
        # l'accueillir, et l'enregistrement echouerait plus tard.
        ancetre = next((a for a in p.parents if a.exists()), None)
        if ancetre is None or not ancetre.is_dir() or not os.access(ancetre, os.W_OK):
            reponse["message"] = f"Emplacement introuvable ou non inscriptible : {p}"
            return reponse
        reponse["ok"] = True
        reponse["creable"] = True
        reponse["message"] = f"Ce dossier n'existe pas encore et sera créé : {p}"
        return reponse
    except (OSError, ValueError) as e:
        reponse["message"] = f"Chemin invalide : {e}"
        return reponse

@router.get("/verifier-dossier")
async def verifier_dossier(chemin: str = Query("", max_length=400)):
    return await asyncio.to_thread(_sonder_dossier, chemin)

@router.get("")
async def get_settings():
    return await asyncio.to_thread(load_settings)

@router.post("")
async def update_settings(body: SettingsBody):
    s = await asyncio.to_thread(load_settings)

    if body.qualite is not None:
        if body.qualite not in QUALITES_VALIDES:
            return {"ok": False, "message": f"Qualité invalide (attendu: {sorted(QUALITES_VALIDES)})"}
        s["qualite"] = body.qualite

    if body.thread_count is not None:
        try:
            s["thread_count"] = max(1, min(32, int(body.thread_count)))
        except (TypeError, ValueError):
            return {"ok": False, "message": "thread_count doit être un entier"}

    downloads_dir_changed = False
    if body.downloads_dir is not None and body.downloads_dir != s.get("downloads_dir"):
        ok, val = await asyncio.to_thread(_valider_dossier, body.downloads_dir)
        if not ok:
            return {"ok": False, "message": val}
        s["downloads_dir"] = val
        downloads_dir_changed = True

    scans_dir_changed = False
    if body.scans_dir is not None and body.scans_dir != s.get("scans_dir"):
        ok, val = await asyncio.to_thread(_valider_dossier, body.scans_dir)
        if not ok:
            return {"ok": False, "message": val}
        s["scans_dir"] = val
        scans_dir_changed = True

    if body.notifications is not None:
        s["notifications"] = bool(body.notifications)

    if body.son_notif is not None:
        s["son_notif"] = bool(body.son_notif)
    if body.confirm_suppr is not None:
        s["confirm_suppr"] = bool(body.confirm_suppr)
    if body.skip_existants is not None:
        s["skip_existants"] = bool(body.skip_existants)
    if body.langue_defaut is not None:
        lang = str(body.langue_defaut).upper().strip()
        if lang in ("VOSTFR", "VF"):
            s["langue_defaut"] = lang

    if not await asyncio.to_thread(save_settings, s):
        return {"ok": False, "message": "Sauvegarde impossible (disque ?)"}

    if downloads_dir_changed or scans_dir_changed:
        try:
            from engine.config.settings import (
                invalider_downloads_dir_cache,
                invalider_scans_dir_cache,
            )
            from engine.library.scanner import invalider_cache_dossiers, invalider_cache_librairie
            from engine.library.updates import invalider_cache_updates
            if downloads_dir_changed:
                invalider_downloads_dir_cache()
            if scans_dir_changed:
                invalider_scans_dir_cache()
            invalider_cache_dossiers()
            invalider_cache_librairie()
            # check_updates_async rescanne la librairie en direct, mais son
            # propre cache de 300 s servait le verdict calcule sur l'ancien
            # dossier. Invalider un maillon sans son aval ne sert a rien.
            invalider_cache_updates()
            log.debug("Cache dossiers/librairie/updates invalidé (changement de dossier)")
        except Exception as e:
            log.debug(f"Invalidation cache dossiers : {e}")

    if any([body.qualite is not None, body.thread_count is not None, downloads_dir_changed]):
        try:
            import engine.download.methods.nm3u8dl as _nm3
            _nm3.invalider_cache_settings()
            log.debug("Cache settings nm3u8dl invalidé")
        except Exception as e:
            log.debug(f"Invalidation cache nm3u8dl : {e}")

    log.success("Paramètres mis à jour")  # type: ignore[attr-defined]
    log.debug(f"Nouveaux paramètres : {s}")
    return {"ok": True, "settings": s}
