import os
import sys
import tempfile
import threading
from typing import Any

sys.dont_write_bytecode = True

import server

TITRE = "Anime-Sama"

# La desinstallation appelle l'exe avec cette option pour reprendre la cle Fernet
# de cette installation : le trousseau Windows survit a la suppression de {app},
# et Inno ne sait pas recalculer le nom derive du chemin d'installation.
OPTION_PURGE_TROUSSEAU = "--purge-keyring"

# Un premier lancement apres rebuild fait analyser 1,2 Go de bundle par
# l'antivirus avant que le premier octet de Python ne s'execute : 10 s ne
# suffisaient pas et la fenetre se fermait sans rien dire. Les sources, elles,
# demarrent en deux secondes.
ATTENTE_PAQUET_S = 120.0
ATTENTE_SOURCES_S = 25.0

_CHEMIN_LOG = os.path.join(tempfile.gettempdir(), "anime_sama_desktop.log")

# Embarque en base64 : cet ecran s'affiche avant que le serveur ne reponde,
# donc aucune requete vers /img/ ne peut aboutir. 600x600 en WebP q85,
# 14 ko une fois encode.
_VISUEL_ATTENTE = "data:image/webp;base64,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"

_STYLE = """
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin:0; height:100vh; display:flex; align-items:center;
         justify-content:center; background:#0d0b14; color:#e8e6f0;
         font-family:"Segoe UI",system-ui,sans-serif; text-align:center; }
  main { max-width:34rem; padding:2rem; }
  h1 { font-size:1.35rem; font-weight:600; margin:0 0 .75rem; }
  p { margin:.4rem 0; color:#a9a4bd; line-height:1.55; font-size:.95rem; }
  .visuel { width:min(58vmin,300px); height:auto; display:block; margin:0 auto 1.25rem;
            border-radius:12px; }
  @media (max-height:560px) { .visuel { display:none; } }
  .anneau { width:38px; height:38px; margin:0 auto 1.25rem; border-radius:50%;
            border:3px solid #2a2338; border-top-color:#8b5cf6;
            animation:tourne 1s linear infinite; }
  @keyframes tourne { to { transform:rotate(360deg); } }
  @media (prefers-reduced-motion:reduce) { .anneau { animation-duration:3s; } }
  .compteur { font-variant-numeric:tabular-nums; color:#6f6a85; font-size:.85rem;
              margin-top:1.25rem; }
  .alerte { color:#f87171; font-weight:600; }
  code { background:#1a1626; padding:.15rem .4rem; border-radius:4px;
         font-size:.85em; color:#c4b5fd; word-break:break-all; }
"""

_PAGE_ATTENTE = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>{TITRE}</title><style>{_STYLE}</style></head><body><main>
<img class="visuel" src="{_VISUEL_ATTENTE}" alt="" />
<div class="anneau"></div>
<h1>Démarrage d'Anime-Sama…</h1>
<p id="detail">Ouverture du serveur local.</p>
<p class="compteur" id="compteur">0 s</p>
</main><script>
var t0 = Date.now();
var detail = document.getElementById('detail');
var compteur = document.getElementById('compteur');
setInterval(function () {{
  var s = Math.floor((Date.now() - t0) / 1000);
  compteur.textContent = s + ' s';
  if (s === 8) detail.textContent =
    "Premier lancement après une mise à jour : l'antivirus analyse le paquet. "
    + "C'est normal, cela peut prendre une minute.";
  if (s === 45) detail.textContent =
    "Toujours en cours — l'analyse antivirus d'un bundle de 1,2 Go est lente "
    + "sur un disque mécanique.";
}}, 250);
</script></body></html>"""


def _page_erreur(message: str) -> str:
    from html import escape
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>{TITRE}</title><style>{_STYLE}</style></head><body><main>
<h1 class="alerte">Anime-Sama n'a pas pu démarrer</h1>
<p>{escape(message)}</p>
<p>Journal complet : <code>{escape(_CHEMIN_LOG)}</code></p>
</main></body></html>"""


def _budget_attente() -> float:
    return ATTENTE_PAQUET_S if getattr(sys, "frozen", False) else ATTENTE_SOURCES_S


def _peut_afficher_boite() -> bool:
    """Une boite de dialogue ne remplace la console que la ou il n'y en a pas.

    En build fenetre (frozen), sys.stderr est detourne vers
    %TEMP%\\anime_sama_desktop.log : s'y limiter revient a ne rien dire du tout.
    Lance depuis un terminal, le message est deja lisible a l'ecran.
    """
    if sys.platform != "win32" or os.environ.get("ANIMESAMA_NO_DIALOG"):
        return False
    return bool(getattr(sys, "frozen", False))


def _signaler_echec(message: str) -> None:
    server.log.error(message)
    if not _peut_afficher_boite():
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, f"{message}\n\nJournal : {_CHEMIN_LOG}", f"{TITRE} — démarrage impossible",
            0x00000010 | 0x00040000,
        )
    except Exception:
        server.log.debug("boîte de dialogue native indisponible", exc_info=True)


def _message_echec(budget: float) -> str:
    cause = server.erreur_demarrage()
    if cause:
        return f"Le serveur local s'est arrêté sur une erreur : {cause}"
    return (
        f"Le serveur local n'a pas répondu sur le port attendu après {int(budget)} s. "
        "Une autre application occupe peut-être ce port, ou l'antivirus bloque "
        "l'exécutable."
    )


def _rejoindre_serveur(fenetre, url: str, arret: threading.Event) -> None:
    budget = _budget_attente()

    def _progres(ecoule: float, total: float) -> None:
        server.log.info(f"Démarrage du serveur… {int(ecoule)}s / {int(total)}s")

    if server.wait_for_server(timeout=budget, on_attente=_progres, arret=arret):
        fenetre.load_url(url)
        return
    if arret.is_set():
        return
    message = _message_echec(budget)
    server.log.error(message)
    try:
        fenetre.load_html(_page_erreur(message))
    except Exception:
        server.log.debug("affichage de la page d'erreur impossible", exc_info=True)
        _signaler_echec(message)


class PontNatif:
    """Ce que la fenetre de bureau sait faire et pas un navigateur.

    pywebview reinjecte `window.pywebview` a chaque `on_navigation_completed` :
    le pont survit donc au passage de la page d'attente a l'URL du serveur. Le
    front teste sa presence et retombe sur le champ texte quand l'interface est
    ouverte depuis un navigateur, ou l'objet n'existe pas.
    """

    # Prefixe souligne obligatoire : pywebview publie tout attribut public de
    # l'objet js_api et *descend* dans ceux qui ne sont pas appelables. Une
    # `fenetre` publique exposerait toutes les methodes de Window a la page,
    # et ferait reparcourir l'objet a chaque navigation.
    def __init__(self) -> None:
        self._fenetre: Any = None

    def choisir_dossier(self, depart: str = "") -> str:
        import webview

        fen = self._fenetre or (webview.windows[0] if webview.windows else None)
        if fen is None:
            return ""
        try:
            choix = fen.create_file_dialog(
                webview.FOLDER_DIALOG, directory=depart or "",
            )
        except Exception:
            server.log.debug("selecteur de dossier natif indisponible", exc_info=True)
            return ""
        if not choix:
            return ""
        return str(choix[0]) if isinstance(choix, (list, tuple)) else str(choix)


def _purger_trousseau() -> None:
    from engine.auth import storage
    try:
        storage.purger_cle_installation()
    except Exception:
        server.log.debug("purge du trousseau impossible", exc_info=True)


def main() -> None:
    if OPTION_PURGE_TROUSSEAU in sys.argv[1:]:
        _purger_trousseau()
        return

    from engine.config.settings import HOST, PORT
    url = f"http://{HOST}:{PORT}"

    try:
        import webview
    except ImportError:
        _signaler_echec("pywebview est requis pour l'application de bureau (pip install pywebview)")
        raise SystemExit(1) from None

    pont = PontNatif()

    deja_actif = server.wait_for_server(timeout=0.6)
    if deja_actif:
        from engine.version import empreinte_installation

        if server.installation_en_ecoute() == empreinte_installation():
            server.log.info("Serveur déjà en cours sur %s — la fenêtre s'y connecte", url)
            pont._fenetre = webview.create_window(
                TITRE, url, width=1280, height=860, min_size=(900, 600), js_api=pont,
            )
            webview.start()
            return
        # Le port est commun aux sources, au build et a l'application installee
        # (lancee au demarrage de Windows si l'option est cochee) : s'y brancher
        # montrait l'ancien paquet a qui croyait tester ses sources.
        message = (
            f"Le port {PORT} est déjà pris par une autre installation d'Anime-Sama "
            "ou par un autre programme. Ferme-la, ou lance celle-ci sur un autre port "
            "avec la variable PORT (par exemple PORT=7844)."
        )
        server.log.error(message)
        webview.create_window(
            TITRE, html=_page_erreur(message), width=1280, height=860, min_size=(900, 600),
        )
        webview.start()
        return

    if not server._verifier_static_dir():
        _signaler_echec(
            "Les fichiers de l'interface sont introuvables — l'installation est incomplète."
        )
        sys.exit(1)
    server.purger_logs_nm3u8dl(max_fichiers=20)
    threading.Thread(target=server.start_server, daemon=True, name="uvicorn").start()
    threading.Thread(target=server.restore_session, daemon=True, name="restore").start()

    arret = threading.Event()
    fenetre = webview.create_window(
        TITRE, html=_PAGE_ATTENTE, width=1280, height=860, min_size=(900, 600), js_api=pont,
    )
    if fenetre is None:
        _signaler_echec("La fenêtre de l'application n'a pas pu être créée.")
        sys.exit(1)
    pont._fenetre = fenetre
    try:
        fenetre.events.closed += lambda: arret.set()
    except Exception:
        server.log.debug("événement de fermeture indisponible", exc_info=True)
    webview.start(_rejoindre_serveur, (fenetre, url, arret))

    arret.set()
    server.cancel_active_download()
    server.stop_server_gracefully()

if __name__ == "__main__":
    main()
