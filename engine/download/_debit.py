"""Abandon d'un telechargement anormalement lent, au profit du lecteur suivant.

STALL_TIMEOUT ne coupe qu'a activite *nulle* : un hebergeur qui bride a 0,2 Mo/s
reste « actif » et occupe le worker pendant des heures. Mesure fournie par
l'utilisateur, meme anime et meme hote (video.sibnet.ru) : 248 Mo en 28 s pour
E001, 197 Mo en 17 min 17 pour E002. Le second est compte comme un succes.

Ce module fournit le token qui coupe. Trois garde-fous, dans cet ordre :

- on ne coupe que si un autre lecteur reste a essayer — sinon un abandon
  transforme un telechargement lent en echec ;
- on ne coupe pas ce qui est presque fini : la decision se prend sur le *reste
  estime*, pas sur le debit seul ;
- le seuil s'adapte : il monte quand cet hote (ou ce meme telechargement) a deja
  fait mieux, plafonne pour qu'un hote tres rapide ne disqualifie pas tout le
  reste. Une ligne lente n'est pas un hote qui bride, et seule la comparaison
  avec ce qu'on a *deja obtenu* permet de les distinguer.

Le token expose `__bool__`/`__getitem__`/`is_cancelled` comme CancelToken : les
moteurs le testent via `cancelled[0]` et tuent le process sans rien savoir de la
regle. C'est l'appelant qui, en rattrapant DownloadCancelled, lit
`abandon_lenteur` pour distinguer un abandon pour lenteur d'une annulation
utilisateur.

La regle ne voit que les telechargements ou yt-dlp mesure lui-meme le debit,
c'est-a-dire ceux *sans* aria2c : avec `--downloader aria2c` la progression
chiffree n'apparait plus sur stdout. Ce n'est pas une lacune — les deux seuls
hotes marques `no_aria2c` (sibnet, sendvid) sont justement ceux qui brident une
connexion unique, et le multi-connexions d'aria2c est deja la reponse ailleurs.
"""

import logging
import threading
import time
from typing import Any

from engine.config.settings import (
    DEBIT_ABANDON_ACTIF,
    DEBIT_DEMARRAGE_S,
    DEBIT_FENETRE_S,
    DEBIT_FRACTION_REF,
    DEBIT_MAX_ABANDONS,
    DEBIT_PLAFOND_MO_S,
    DEBIT_PLANCHER_MO_S,
    DEBIT_RESTE_MIN_S,
)
from engine.download._engine_utils import fmt_speed, token_annule

log = logging.getLogger("engine.download.debit")

MO = 1024.0 * 1024.0
PLANCHER_BPS = DEBIT_PLANCHER_MO_S * MO
PLAFOND_BPS = DEBIT_PLAFOND_MO_S * MO
PCT_MAX_ABANDON = 85.0

_HOTES_MAX = 200
_LENT_TTL = 1800.0

_lock = threading.Lock()
_meilleurs: dict[str, float] = {}
_lents: dict[str, float] = {}


def _purger_verrou_tenu(table: dict[str, float]) -> None:
    if len(table) <= _HOTES_MAX:
        return
    surplus = len(table) - _HOTES_MAX
    for cle, _ in sorted(table.items(), key=lambda kv: kv[1])[:surplus]:
        table.pop(cle, None)


def noter_debit_hote(hote: str, bps: float) -> None:
    if not hote or bps <= 0:
        return
    with _lock:
        if bps > _meilleurs.get(hote, 0.0):
            _meilleurs[hote] = bps
        _purger_verrou_tenu(_meilleurs)


def meilleur_debit_hote(hote: str) -> float:
    if not hote:
        return 0.0
    with _lock:
        return _meilleurs.get(hote, 0.0)


def marquer_hote_lent(hote: str) -> None:
    if not hote:
        return
    with _lock:
        _lents[hote] = time.monotonic() + _LENT_TTL
        _purger_verrou_tenu(_lents)


def hote_lent(hote: str) -> bool:
    if not hote:
        return False
    with _lock:
        jusqua = _lents.get(hote)
        if jusqua is None:
            return False
        if time.monotonic() >= jusqua:
            _lents.pop(hote, None)
            return False
        return True


def reinitialiser() -> None:
    with _lock:
        _meilleurs.clear()
        _lents.clear()


class SurveillantDebit:

    def __init__(
        self,
        base: Any,
        hote: str = "",
        alternatives: int = 0,
        actif: bool = DEBIT_ABANDON_ACTIF,
    ) -> None:
        self._base = base
        self._hote = hote or ""
        self._actif = bool(actif) and alternatives > 0
        self._abandon = False
        self._motif = ""
        self._t0: float | None = None
        self._observe_depuis: float | None = None
        self._pic = 0.0
        self._fenetre: list[tuple[float, float, float]] = []

    def __bool__(self) -> bool:
        return self._abandon or token_annule(self._base)

    def __getitem__(self, _index: int) -> bool:
        return self.__bool__()

    def is_cancelled(self) -> bool:
        return self.__bool__()

    @property
    def abandon_lenteur(self) -> bool:
        return self._abandon

    @property
    def motif(self) -> str:
        return self._motif

    def _reference(self) -> float:
        return max(self._pic, meilleur_debit_hote(self._hote))

    def _seuil(self) -> float:
        adaptatif = DEBIT_FRACTION_REF * self._reference()
        return min(max(PLANCHER_BPS, adaptatif), PLAFOND_BPS)

    def _reste_estime(self, maintenant: float, pct: float) -> float:
        t_vieux, pct_vieux, _ = self._fenetre[0]
        avance = pct - pct_vieux
        ecoule = maintenant - t_vieux
        if avance <= 0 or ecoule <= 0:
            return float("inf")
        return (100.0 - pct) * ecoule / avance

    def _redemarrer_observation(self, maintenant: float) -> None:
        # yt-dlp repart a 0 % pour chaque piste d'un format fusionne : sans ce
        # reset, l'avance devient negative et le reste estime part a l'infini.
        self._fenetre.clear()
        self._observe_depuis = maintenant

    def signaler_debit(self, pct: float, bps: float) -> None:
        maintenant = time.monotonic()
        if self._t0 is None:
            self._t0 = maintenant
        if bps > self._pic:
            self._pic = bps
            noter_debit_hote(self._hote, bps)
        if self._abandon or not self._actif or bps <= 0:
            return
        if maintenant - self._t0 < DEBIT_DEMARRAGE_S:
            return

        if self._observe_depuis is None or (self._fenetre and pct < self._fenetre[-1][1]):
            self._redemarrer_observation(maintenant)

        self._fenetre.append((maintenant, pct, bps))
        limite = maintenant - DEBIT_FENETRE_S
        while len(self._fenetre) > 2 and self._fenetre[1][0] <= limite:
            self._fenetre.pop(0)
        if maintenant - (self._observe_depuis or maintenant) < DEBIT_FENETRE_S:
            return

        moyen = sum(e[2] for e in self._fenetre) / len(self._fenetre)
        seuil = self._seuil()
        if moyen >= seuil or pct >= PCT_MAX_ABANDON:
            return
        reste = self._reste_estime(maintenant, pct)
        if reste < DEBIT_RESTE_MIN_S:
            return

        self._abandon = True
        reste_txt = "inconnu" if reste == float("inf") else f"{int(reste // 60)} min"
        self._motif = (
            f"{self._hote or 'hôte'} ne délivre que {fmt_speed(moyen)} "
            f"(seuil {fmt_speed(seuil)}, encore ~{reste_txt} à ce rythme) — "
            "passage au lecteur suivant"
        )
        log.warning("Débit trop faible : %s", self._motif)


class PolitiqueDebit:
    """Compteur d'abandons pour un episode : deux au plus, sinon on s'acharne."""

    def __init__(
        self,
        alternatives: int = 0,
        actif: bool = DEBIT_ABANDON_ACTIF,
        max_abandons: int = DEBIT_MAX_ABANDONS,
    ) -> None:
        self.alternatives = max(0, int(alternatives))
        self._actif = bool(actif)
        self._max = max(0, int(max_abandons))
        self._abandons = 0

    @property
    def abandons(self) -> int:
        return self._abandons

    def surveillant(self, base: Any, hote: str, alternatives: int) -> SurveillantDebit:
        restantes = max(0, int(alternatives)) + self.alternatives
        actif = self._actif and self._abandons < self._max
        return SurveillantDebit(base, hote=hote, alternatives=restantes, actif=actif)

    def enregistrer_abandon(self, hote: str) -> None:
        self._abandons += 1
        marquer_hote_lent(hote)
