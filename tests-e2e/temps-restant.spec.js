import { expect, test } from "@playwright/test";

// Le temps restant etait invente a deux endroits : `ETA 00:32` attrape au lasso
// dans la sortie de yt-dlp — absente des trois autres moteurs — et `totalEps * 8`
// pour la file, huit minutes par episode quelle que soit la connexion.
//
// utils/eta.js mesure a la place. Ces tests pilotent l'horloge du navigateur :
// sans page.clock il faudrait attendre les vraies minutes, et les seuils du
// module (5 s d'observation minimum, fenetre d'une minute) rendraient la mesure
// impossible a verifier autrement qu'en dormant.

const charger = async (page) => {
  await page.clock.install();
  await page.goto("/");
  await page.evaluate(async () => {
    window.__eta = await import("/js/utils/eta.js");
    window.__eta._reinitialiser();
  });
};

const appel = (page, code) => page.evaluate(code);

test("le reste se deduit de l'avancement, quel que soit le moteur", async ({ page }) => {
  await charger(page);

  await appel(page, () => {
    window.__eta.demarrerEpisode({ index: 0, total: 1 });
    window.__eta.noterProgression(0);
  });

  // Rien avant 5 s d'observation : deux points colles ne mesurent rien.
  expect(await appel(page, () => window.__eta.resteEpisodeS())).toBeNull();

  await page.clock.fastForward(10_000);
  await appel(page, () => window.__eta.noterProgression(10));

  // 10 % en 10 s -> 1 %/s -> 90 s pour les 90 % restants.
  const reste = await appel(page, () => window.__eta.resteEpisodeS());
  expect(reste).toBeGreaterThan(85);
  expect(reste).toBeLessThan(95);
});

test("le reste descend tout seul entre deux lignes du moteur", async ({ page }) => {
  // C'est ce qui fait « 30 min puis 28 puis 25 » : sans le temps ecoule depuis
  // le dernier evenement, le chiffre resterait fige jusqu'a la ligne suivante.
  await charger(page);
  await appel(page, () => {
    window.__eta.demarrerEpisode({ index: 0, total: 1 });
    window.__eta.noterProgression(0);
  });
  await page.clock.fastForward(10_000);
  await appel(page, () => window.__eta.noterProgression(10));

  const avant = await appel(page, () => window.__eta.resteEpisodeS());
  await page.clock.fastForward(30_000);
  const apres = await appel(page, () => window.__eta.resteEpisodeS());

  expect(avant - apres).toBeGreaterThan(25);
  expect(avant - apres).toBeLessThan(35);
});

test("le pourcentage qui repart a zero ne fait pas exploser l'estimation", async ({ page }) => {
  // yt-dlp recommence a 0 % pour chaque piste d'un format fusionne. Sans remise
  // a zero de la fenetre, l'avance devient negative et le reste part a l'infini.
  await charger(page);
  await appel(page, () => {
    window.__eta.demarrerEpisode({ index: 0, total: 1 });
    window.__eta.noterProgression(0);
  });
  await page.clock.fastForward(10_000);
  await appel(page, () => window.__eta.noterProgression(80));

  await page.clock.fastForward(1000);
  await appel(page, () => window.__eta.noterProgression(0)); // seconde piste
  await page.clock.fastForward(10_000);
  await appel(page, () => window.__eta.noterProgression(20));

  const reste = await appel(page, () => window.__eta.resteEpisodeS());
  expect(reste).not.toBeNull();
  expect(Number.isFinite(reste)).toBe(true);
  expect(reste).toBeLessThan(600);
});

test("la mediane des durees vient des episodes reellement termines", async ({ page }) => {
  await charger(page);

  for (const secondes of [100, 200, 900]) {
    await appel(page, () => window.__eta.demarrerEpisode({ index: 0, total: 1 }));
    await page.clock.fastForward(secondes * 1000);
    await appel(page, () => window.__eta.terminerEpisode(true));
  }
  // Le dernier cycle se clot quand la file se vide.
  await appel(page, () => window.__eta.arreterEpisode());

  // La mediane, pas la moyenne : l'episode a 900 s sur un hote bride ne doit pas
  // tirer l'estimation des autres (la moyenne donnerait 400).
  expect(await appel(page, () => window.__eta.dureeMedianeEpisodeS())).toBe(200);
  expect(await appel(page, () => window.__eta.estMesuree())).toBe(true);
  expect(await appel(page, () => window.__eta.nbEchantillons())).toBe(3);
});

test("echecs, sauts et pauses ne polluent pas la mediane", async ({ page }) => {
  await charger(page);

  // Un echec : l'episode s'est arrete en route, sa duree ne dit rien.
  await appel(page, () => window.__eta.demarrerEpisode({ index: 0, total: 1 }));
  await page.clock.fastForward(300_000);
  await appel(page, () => window.__eta.terminerEpisode(false));

  // Une pause : l'horloge a tourne, l'avancement non.
  await appel(page, () => window.__eta.demarrerEpisode({ index: 0, total: 1 }));
  await page.clock.fastForward(60_000);
  await appel(page, () => window.__eta.signalerPause(true));
  await page.clock.fastForward(600_000);
  await appel(page, () => window.__eta.terminerEpisode(true));

  // Un saut : quelques millisecondes, sous le plancher de l'echantillon.
  await appel(page, () => window.__eta.demarrerEpisode({ index: 0, total: 1 }));
  await page.clock.fastForward(200);
  await appel(page, () => window.__eta.terminerEpisode(true));
  await appel(page, () => window.__eta.arreterEpisode());

  expect(await appel(page, () => window.__eta.nbEchantillons())).toBe(0);
  expect(await appel(page, () => window.__eta.estMesuree())).toBe(false);
});

test("sans aucune mesure, le repli reste les huit minutes historiques", async ({ page }) => {
  await charger(page);
  expect(await appel(page, () => window.__eta.dureeMedianeEpisodeS())).toBe(480);
  expect(await appel(page, () => window.__eta.estMesuree())).toBe(false);
});

test("le total couvre l'episode en cours, ses suivants, puis la file", async ({ page }) => {
  await charger(page);

  // Une mediane connue : deux echantillons de 120 s.
  for (let i = 0; i < 2; i++) {
    await appel(page, () => window.__eta.demarrerEpisode({ index: 0, total: 1 }));
    await page.clock.fastForward(120_000);
    await appel(page, () => window.__eta.terminerEpisode(true));
  }

  // Episode 1 sur 3 d'un anime, plus 4 episodes en file.
  await appel(page, () => {
    window.__eta.demarrerEpisode({ index: 0, total: 3 });
    window.__eta.noterProgression(0);
  });
  await page.clock.fastForward(10_000);
  await appel(page, () => window.__eta.noterProgression(50)); // 10 s pour la moitie

  expect(await appel(page, () => window.__eta.episodesRestantsItemCourant())).toBe(2);

  // ~10 s de reste + (2 + 4) episodes x 120 s = ~730 s.
  const total = await appel(page, () => window.__eta.resteTotalS(4));
  expect(total).toBeGreaterThan(715);
  expect(total).toBeLessThan(745);
});

test("les durees se lisent en francais, de la seconde a l'heure", async ({ page }) => {
  await charger(page);
  const rendus = await appel(page, () => [
    window.__eta.fmtReste(null),
    window.__eta.fmtReste(45),
    window.__eta.fmtReste(1680),
    window.__eta.fmtReste(3600),
    window.__eta.fmtReste(4500),
  ]);
  expect(rendus).toEqual(["", "45 s", "28 min", "1 h", "1 h 15"]);
});

// ── Corrections du 07/11/2026, d'apres le rejeu d'un vrai telechargement ──────

test("la pause entre deux episodes compte dans leur duree", async ({ page }) => {
  // Mesure du seul episode, l'echantillon oubliait la pause qui le suit
  // (3 s, jusqu'a 33 s d'anti-ban) : l'estimation restait trop basse d'autant.
  await charger(page);
  await appel(page, () => window.__eta.demarrerEpisode({ index: 0, total: 2 }));
  await page.clock.fastForward(100_000);
  await appel(page, () => window.__eta.terminerEpisode(true));
  await page.clock.fastForward(30_000);
  await appel(page, () => window.__eta.demarrerEpisode({ index: 1, total: 2 }));
  expect(await appel(page, () => window.__eta.dureeMedianeEpisodeS())).toBe(130);
});

test("entre deux episodes, le reste de l'anime ne disparait pas", async ({ page }) => {
  await charger(page);
  await appel(page, () => {
    localStorage.setItem("dl_durees_episodes", JSON.stringify([100]));
    window.__eta.demarrerEpisode({ index: 0, total: 3 });
    window.__eta.terminerEpisode(true);
    // Le worker annonce sa pause anti-ban a 0 % APRES la fin de l'episode.
    window.__eta.noterProgression(0);
  });
  expect(await appel(page, () => window.__eta.episodesRestantsItemCourant())).toBe(2);
  expect(await appel(page, () => window.__eta.resteEpisodeS())).toBeNull();
  expect(await appel(page, () => window.__eta.resteAnimeS())).toBe(200);
});

test("une interface ouverte en cours de route retrouve sa place dans l'anime", async ({ page }) => {
  // Sans episode_start vu, elle se croyait au premier et dernier episode.
  await charger(page);
  await appel(page, () => window.__eta.synchroniserFile({ en_cours: { index_episode: 4, nb_episodes: 10 } }));
  expect(await appel(page, () => window.__eta.episodesRestantsItemCourant())).toBe(5);
  await appel(page, () => window.__eta.synchroniserFile({ en_cours: { nb_episodes: 10 } }));
  expect(await appel(page, () => window.__eta.episodesRestantsItemCourant())).toBe(5);
});

test("avant le premier pourcentage, le reste decompte au lieu de rester fige", async ({ page }) => {
  // L'episode cherche son flux 25 a 70 s sans un pourcentage : la mediane
  // conditionnelle (durees deja vues qui depassent le temps ecoule) decompte.
  await charger(page);
  await appel(page, () => {
    localStorage.setItem("dl_durees_episodes", JSON.stringify([30, 100, 100]));
    window.__eta.demarrerEpisode({ index: 0, total: 1 });
  });
  expect(await appel(page, () => window.__eta.resteAnimeS())).toBeCloseTo(100, 0);
  await page.clock.fastForward(40_000);
  // 30 s n'est plus plausible apres 40 s : reste = 100 - 40.
  const reste = await appel(page, () => window.__eta.resteAnimeS());
  expect(reste).toBeGreaterThan(58);
  expect(reste).toBeLessThan(62);
  await page.clock.fastForward(200_000);
  // Au-dela de tout ce qu'on a vu : un plancher, jamais « 0 s ».
  expect(await appel(page, () => window.__eta.resteAnimeS())).toBeCloseTo(10, 0);
});
