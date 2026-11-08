import logging
import sys
import time

sys.dont_write_bytecode = True

from engine.config.logging_setup import maybe_install_file_logging, setup_logging

setup_logging(level=logging.INFO)
maybe_install_file_logging()

log = logging.getLogger("main")

def purger_logs_nm3u8dl(max_fichiers: int = 20) -> None:
    try:
        from pathlib import Path

        from engine.download.methods.nm3u8dl import NM3U8DL_LOG_CWD
        logs_dir = Path(NM3U8DL_LOG_CWD) / "Logs"
        if not logs_dir.is_dir():
            return

        def _safe_mtime(f):
            try:
                return f.stat().st_mtime
            except OSError:
                return 0.0

        fichiers = sorted(
            logs_dir.glob("*.log"),
            key=_safe_mtime,
            reverse=True,
        )
        a_supprimer = fichiers[max_fichiers:]
        for f in a_supprimer:
            try:
                f.unlink()
            except OSError:
                pass
        if a_supprimer:
            log.info(f"Logs nm3u8dl : {len(a_supprimer)} ancien(s) supprimé(s), "
                     f"{min(len(fichiers), max_fichiers)} conservé(s)")
    except Exception as e:
        log.debug(f"purger_logs_nm3u8dl : {e}")

def journaliser_identite_build() -> None:
    try:
        from engine.version import description_build
        log.info(f"Anime-Sama {description_build()}")
    except Exception as e:
        log.debug(f"journaliser_identite_build : {e}")

def bundle_perime() -> str:
    """Sources JS plus recentes que le bundle : le navigateur sert l'ancien code.

    Muet en mode frozen — le paquet n'embarque pas web/static/js, il n'y a donc
    rien a comparer et l'ecart y est celui du paquet vs l'installation, mesure
    par packaging/verifier_installation.py.
    """
    if getattr(sys, "frozen", False):
        return ""
    try:
        from pathlib import Path

        from engine.config.settings import STATIC_DIR
        bundle = STATIC_DIR / "dist" / "app.js"
        if not bundle.is_file():
            return ""
        t_bundle = bundle.stat().st_mtime
        sources: list[Path] = [
            f for f in (STATIC_DIR / "js").rglob("*.js") if f.is_file()
        ]
        recentes = [f for f in sources if f.stat().st_mtime > t_bundle + 1.0]
        if not recentes:
            return ""
        plus_recente = max(recentes, key=lambda f: f.stat().st_mtime)
        return (
            f"{len(recentes)} fichier(s) de web/static/js modifiés depuis la dernière "
            f"construction du bundle (le plus récent : {plus_recente.name})"
        )
    except OSError as e:
        log.debug(f"bundle_perime : {e}")
        return ""

def avertir_si_bundle_perime() -> None:
    motif = bundle_perime()
    if motif:
        log.warning(
            f"Bundle front périmé : {motif}.\n"
            "→ L'interface servira l'ancien code tant que « npm run build » n'a pas "
            "été relancé."
        )

def _verifier_static_dir() -> bool:
    try:
        from engine.config.settings import STATIC_DIR
        if not STATIC_DIR.is_dir():
            log.error(
                f"Dossier 'static/' introuvable : {STATIC_DIR}\n"
                "→ Vérifiez que l'installation est complète (tous les fichiers "
                "du dépôt sont présents)."
            )
            return False
        if not (STATIC_DIR / "index.html").exists():
            log.warning(
                "static/index.html introuvable — l'interface web pourrait "
                "ne pas s'afficher correctement."
            )
        if not (STATIC_DIR / "dist" / "app.js").exists():
            log.error(
                "Bundle front absent : static/dist/app.js introuvable — "
                "l'interface s'affichera en page blanche.\n"
                "→ Construisez-le avec « npm install » puis « npm run build »."
            )
        return True
    except Exception as e:
        log.warning(f"_verifier_static_dir : {e}")
        return True

_MOTEURS_LABELS = {
    "nm3u8dl": "N_m3u8DL-RE",
    "ytdlp": "yt-dlp",
    "ffmpeg": "ffmpeg",
}

def _moteurs_presents() -> dict:
    from engine.download.methods.ffmpeg_engine import _get_ffmpeg_path
    from engine.download.methods.nm3u8dl import _get_nm3u8dl_path
    from engine.download.methods.ytdlp_engine import _get_ytdlp_path

    return {
        "nm3u8dl": _get_nm3u8dl_path(),
        "ytdlp": _get_ytdlp_path(),
        "ffmpeg": _get_ffmpeg_path(),
    }

def verifier_prerequis() -> list[str]:
    """Bilan unique des binaires au demarrage.

    yt-dlp et ffmpeg ne se signalaient qu'en log.debug : sur une machine vierge
    l'utilisateur ne decouvrait leur absence qu'au premier telechargement rate.
    """
    try:
        presents = _moteurs_presents()
    except Exception as e:
        log.debug(f"verifier_prerequis : {e}")
        return []

    manquants = [_MOTEURS_LABELS[k] for k in ("nm3u8dl", "ytdlp", "ffmpeg")
                 if not presents.get(k)]
    if not manquants:
        return []

    liste = ", ".join(manquants)
    if len(manquants) == 3:
        log.error(
            f"Aucun moteur de téléchargement disponible ({liste} tous absents) — "
            "aucun téléchargement ne pourra aboutir.\n"
            "→ Place les exécutables dans « bin/ », ou relance "
            "« packaging/install.bat »."
        )
    else:
        log.warning(
            f"Moteur(s) de téléchargement absent(s) : {liste} — la cascade "
            "fonctionnera en mode dégradé (moins de sources récupérables).\n"
            "→ Place les exécutables manquants dans « bin/ »."
        )
    return manquants

_server = None
_erreur_demarrage = ""

def erreur_demarrage() -> str:
    """Cause du serveur mort-ne, pour que l'appelant l'affiche au lieu d'un timeout nu."""
    return _erreur_demarrage

def start_server():
    global _server, _erreur_demarrage
    _erreur_demarrage = ""
    try:
        import uvicorn

        from engine.config.settings import HOST, PORT
        from web.api.app import create_app

        journaliser_identite_build()
        avertir_si_bundle_perime()
        verifier_prerequis()

        config = uvicorn.Config(
            create_app(),
            host=HOST,
            port=PORT,
            log_level="warning",
            timeout_graceful_shutdown=5,
        )
        _server = uvicorn.Server(config)
        _server.run()
    except Exception as e:
        _erreur_demarrage = f"{type(e).__name__} : {e}"
        log.error(f"uvicorn s'est arrêté sur erreur : {e}")

def wait_for_server(timeout=10, on_attente=None, arret=None):
    import socket

    from engine.config.settings import HOST, PORT
    t = time.time()
    prochain_signal = t + 3.0
    while True:
        ecoule = time.time() - t
        if ecoule >= timeout:
            return False
        # Le thread d'attente de pywebview n'est pas demon : sans cette sortie,
        # fermer la fenetre pendant l'attente ferait survivre le processus
        # jusqu'au bout du budget.
        if arret is not None and arret.is_set():
            return False
        try:
            socket.create_connection((HOST, PORT), timeout=0.3).close()
            return True
        except OSError:
            if on_attente is not None and time.time() >= prochain_signal:
                prochain_signal = time.time() + 3.0
                try:
                    on_attente(ecoule, timeout)
                except Exception:
                    log.debug("wait_for_server: callback d'attente en échec", exc_info=True)
            time.sleep(0.05)

def installation_en_ecoute(timeout: float = 2.0) -> str:
    """Empreinte de l'installation qui repond sur le port ; "" si inconnue.

    "" couvre aussi bien un paquet d'avant ce champ qu'un autre programme : dans
    les deux cas, ce n'est pas a cette fenetre de s'y brancher.
    """
    import json
    import urllib.request

    from engine.config.settings import HOST, PORT
    # Sans proxy : celui du systeme intercepterait sinon la boucle locale.
    ouvreur = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with ouvreur.open(f"http://{HOST}:{PORT}/api/health", timeout=timeout) as r:
            data = json.loads(r.read(1_000_000))
    except (OSError, ValueError):
        return ""
    build = data.get("build") if isinstance(data, dict) else None
    valeur = build.get("installation") if isinstance(build, dict) else None
    return valeur if isinstance(valeur, str) else ""

def restore_session():
    try:
        from engine.auth.manager import auth_manager
        if auth_manager.restore_session():
            log.success(f"Session restaurée — {auth_manager.username or 'utilisateur'}")  # type: ignore[attr-defined]
        else:
            log.info("Aucune session sauvegardée — connexion requise")
    except Exception as e:
        log.warning(f"Restauration session impossible : {e}")

def cancel_active_download():
    try:
        from engine.download.queue import queue
        if queue.statut().get("en_cours"):
            log.info("Arrêt du téléchargement en cours (préservé pour reprise)...")
            queue.shutdown_preserve()
            t = time.time()
            while queue.statut().get("en_cours") and (time.time() - t) < 10:
                time.sleep(0.2)
            if queue.statut().get("en_cours"):
                log.warning("Le worker n'a pas libéré sous 10s — on continue le shutdown")
    except Exception as e:
        log.warning(f"cancel_active_download : {e}")

def stop_server_gracefully():
    global _server
    if _server is None:
        return
    log.info("Arrêt du serveur en cours...")
    try:
        from web.api.routes.sse import request_shutdown
        request_shutdown()
    except Exception as e:
        log.debug(f"stop_server_gracefully (sse) : {e}")
    try:
        _server.should_exit = True
    except Exception as e:
        log.debug(f"stop_server_gracefully : {e}")
