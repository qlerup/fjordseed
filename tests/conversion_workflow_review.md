# Browserkontrol af konverteringsestimater

Udført 5. november 2026 på serverens isolerede Flask-app med Python 3.11.2,
Playwright 1.56.0 og Chromium 141.0.7390.37. Brugte projektets templates,
scripts, CSS og originale baggrundsbilleder. Testafhængigheder blev klargjort
midlertidigt uden nye dependencies i projektet.

Nordic vælges via temaindstillingerne, gemmes, og kontrolleres efter reload.
Samme kontrol køres separat med standardtemaet Fjord. Browserkørslerne køres
sekventielt, og testserveren håndterer de korte requests uden en tråd pr. request,
så kontrollen også kan køre med containerens begrænsede trådantal.

## Udførte kontroller

Begge browserkørsler afsluttede med exitkode 0 ved 1440, 390 og 320 px:

- Tre bitratekort med forventet slutstørrelse, besparelse og størrelsesforøgelse.
- Ingen vandret overflow på siden, bitratekortene eller dialogen.
- Mobilkort bruger hele filmkortets bredde; dette er også en assertion i testen.
- Live-estimat ved ændring af bitrate og begge typer pladsændring i køoversigten.
- Dialogens næste/tilbage-forløb og køindsendelse med 20 og 40 Mbps.
- Spring over/gendan samt særskilte valg for video og lyd.
- Ingen JavaScript-fejl, HTTP 404 eller server-tracebacks i de endelige logs.

Manuel visuel kontrol af skærmbillederne viste, at den tidligere smalle tekstkolonne
på mobil gjorde estimaterne svære at læse. CSS er rettet, så filmoplysninger og
estimater står under rækken med afkrydsning, cover og spring over-knap på mobil.
Nordic-dialogens oprindelige træbaggrund er med i kontrollen.

API-svar og køindsendelse er simuleret. Ingen torrentfiler eller mediefiler ændres,
og testen udfører ingen faktisk konvertering.

## Kommandoer og faktisk output

Kørt i det klargjorte servermiljø (midlertidige Python-, bibliotek- og fontstier
angivet via PYTHONPATH, LD_LIBRARY_PATH og FONTCONFIG_FILE):

```sh
python3 fjordseed/tests/browser_conversion_workflow.py --theme nordic
python3 fjordseed/tests/browser_conversion_workflow.py --theme fjord
node fjordseed/tests/conversion_workflow_estimates.cjs
```

Begge temaer gav følgende PASS-linjer for hver af de tre bredder:

```text
PASS nordic 1440px: savings + growth estimates, no page/card overflow
PASS nordic 390px: savings + growth estimates, no page/card overflow
PASS nordic 320px: savings + growth estimates, no page/card overflow
PASS nordic 1440px: conversion dialog + live savings, no overflow
PASS nordic 390px: conversion dialog + live savings, no overflow
PASS nordic 320px: conversion dialog + live savings, no overflow
PASS nordic 1440px: queue review savings + growth, no overflow
PASS nordic 390px: queue review savings + growth, no overflow
PASS nordic 320px: queue review savings + growth, no overflow
PASS: cards, responsive 1440/390/320, per-film settings, estimates, queue submission, skip/restore, audio/video boundaries; no JS errors
PASS: estimate values, savings and percentage, growth, missing metadata, unchanged audio and zero source size
```

Fuld output: [Nordic](../test-results/conversion-workflow/nordic-browser.log),
[Fjord](../test-results/conversion-workflow/fjord-browser.log) og
[beregninger](../test-results/conversion-workflow/calculations.log).

## Skærmbilleder

| Tema / bredde | Besparelse | Ekstra plads | Dialog | Køoversigt |
| --- | --- | --- | --- | --- |
| Nordic 1440 | [PNG](../test-results/conversion-workflow/nordic-saving-1440.png) | [PNG](../test-results/conversion-workflow/nordic-growth-1440.png) | [PNG](../test-results/conversion-workflow/nordic-modal-1440.png) | [PNG](../test-results/conversion-workflow/nordic-review-1440.png) |
| Nordic 390 | [PNG](../test-results/conversion-workflow/nordic-saving-390.png) | [PNG](../test-results/conversion-workflow/nordic-growth-390.png) | [PNG](../test-results/conversion-workflow/nordic-modal-390.png) | [PNG](../test-results/conversion-workflow/nordic-review-390.png) |
| Nordic 320 | [PNG](../test-results/conversion-workflow/nordic-saving-320.png) | [PNG](../test-results/conversion-workflow/nordic-growth-320.png) | [PNG](../test-results/conversion-workflow/nordic-modal-320.png) | [PNG](../test-results/conversion-workflow/nordic-review-320.png) |
| Fjord 1440 | [PNG](../test-results/conversion-workflow/fjord-saving-1440.png) | [PNG](../test-results/conversion-workflow/fjord-growth-1440.png) | [PNG](../test-results/conversion-workflow/fjord-modal-1440.png) | [PNG](../test-results/conversion-workflow/fjord-review-1440.png) |
| Fjord 390 | [PNG](../test-results/conversion-workflow/fjord-saving-390.png) | [PNG](../test-results/conversion-workflow/fjord-growth-390.png) | [PNG](../test-results/conversion-workflow/fjord-modal-390.png) | [PNG](../test-results/conversion-workflow/fjord-review-390.png) |
| Fjord 320 | [PNG](../test-results/conversion-workflow/fjord-saving-320.png) | [PNG](../test-results/conversion-workflow/fjord-growth-320.png) | [PNG](../test-results/conversion-workflow/fjord-modal-320.png) | [PNG](../test-results/conversion-workflow/fjord-review-320.png) |

Desuden findes oversigtsbilleder som `{tema}-cards-{bredde}.png` og
`{tema}-estimates-{bredde}.png` i samme mappe. De fokuserede filmklip er taget
med filmkortet øverst i viewporten, så den sticky valgbjælke ikke dækker estimaterne.

## Arkivering

Denne rapport beskriver browserkontrollen udført 5. november 2026. Logfiler og
skærmbilleder i test-results er lokale testartefakter og følger ikke med i GitHub-repositoryet.
