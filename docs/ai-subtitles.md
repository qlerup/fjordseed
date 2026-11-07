# AI-oversættelse af undertekster

Under **Indstillinger → Konvertering → AI-oversættelse** vælges film fra det eksisterende bevarede bibliotek. Film under download, flytning eller konvertering kan ikke behandles. Seeder og Originals er ikke med i listen.

For hver film vises indbyggede undertekstspor samt `.srt` og `.sup` med samme grundnavn ved filmen. Sproget læses fra spormetadata eller sprogmærket i filnavnet. Et fuldt engelsk spor foretrækkes; tekst foretrækkes frem for PGS inden for samme sprog. Kildespor og flere målsprog vælges individuelt. Eksisterende sprog kan ikke vælges som nye mål.

Oversatte filer gemmes som `Film.da.srt`, `Film.sv.srt` osv. Et forced-kildespor giver eksempelvis `Film.da.forced.srt`. Videoen og eksisterende undertekster ændres aldrig. Plex/Fjordflix kan kræve en biblioteksopdatering, før nye filer vises.

Efter lagring kontrollerer Fjordseed filerne gennem Fjordflix' egen sidecar-opdagelse og opdaterer det præcise Plex-element. Fjordflix læser sidecars igen ved næste åbning af spor/afspilning; en allerede åben afspiller kan kræve genåbning. På installationer med Plex-linkbibliotek opretter den begrænsede `tools/plex_subtitle_links.py`-tjeneste de tilsvarende SRT-links uden at overskrive eksisterende filer. Den kender kun videoer i den eksisterende links-ledger. Manglende eller tvetydig katalogisering vises som fejl, ikke som succes.

Forbindelser konfigureres i `/data/subtitle-library.json` med filrettighed 0600: `fjordflix_container`, `fjordflix_root`, `plex_url`, `plex_token`, `plex_root`. Linkbiblioteker bruger desuden `plex_link_url`, `plex_link_secret` og `plex_view_root`. Linktjenesten læser bind-adresse, port og hemmelighed fra `/etc/fjordseed-subtitle-links.json` på Plex-serveren. Disse filer indeholder legitimationsoplysninger og må ikke lægges i Git. Manglende konfiguration stopper kun biblioteksopdateringen; allerede gemte undertekster bevares.

## PGS og timing

PGS indeholder billeder, paletter, kompositioner og præsentationstider. Programmet udtrækker SUP med FFmpeg, samler billederne og læser teksten med Tesseract på serveren. Hver komposition afsluttes ved næste komposition/clear. PGS-tider i 90 kHz afrundes til nærmeste millisekund, som SRT understøtter. Et spor med manglende sluttid, beskadigede billeder eller ulæselig tekst fejler frem for at få opdigtede tider. Ukendt OCR-kildesprog forsøges som engelsk.

OpenAI modtager kun tekst og blok-ID'er. Tidskoder opbevares lokalt og sættes på resultatet igen. AI-svar med manglende, ombyttede eller tomme blokke afvises. OCR og oversættelse kan stadig indeholde sproglige fejl; kontrollér resultatet, især ved stiliserede PGS-undertekster.

## ChatGPT-login

Standardlogin bruger den officielle Codex app-server med en enhedskode, ligesom FjordLens. Codex kører på Fjordseed-serveren. Modeller hentes for den valgte konto; listen garanterer ikke modeladgang, som først bekræftes ved en gennemført oversættelse.

1. Klik **Continue with ChatGPT**.
2. Indtast den viste engangskode på OpenAI-siden, som åbnes i en ny fane. Hvis browseren blokerer fanen, brug **Åbn OpenAI-login**.
3. Godkend forbindelsen hos OpenAI. Fjordseed opdaterer automatisk kontoen og modellisten.
4. Login kan annulleres og udløber efter højst ti minutter. Aktiver eventuelt enhedskodelogin i ChatGPTs sikkerhedsindstillinger.

Ingen lokal installation eller terminalkommando er nødvendig. Loginforsøg ligger kun i serverens hukommelse og skal startes igen efter en servergenstart. Eksisterende direkte SIWC-kontoforbindelser virker fortsat gennem den tidligere adapter.

Hver Fjordhub-bruger har egne kontoforbindelser og oversættelsesjobs. Den lokale admin-loginform er én fælles lokal bruger. Konto og model fastholdes i jobbet. Credentials gemmes med ejeradgang i `/data/subtitle-accounts`; denne mappe må ikke deles med andre brugere. Frakobling fjerner lokale Codex-tokens; adgangen kan også fjernes i ChatGPTs indstillinger. Tokenfornyelse må ikke genskabe en frakoblet konto.

Oversættelse bruger en midlertidig Codex-session med tom arbejdsmappe, deaktiverede værktøjer, read-only-sandbox og et JSON-schema. Kun underteksttekst og blok-ID'er sendes. Resultater accepteres først efter en fuldført turn og validering af alle blokke. Serveren kører én app-proces, som ejer loginforsøg og oversættelseskø.

Listen viser kun medier med fundne undertekstspor. Medier uden kendte spor undersøges i baggrunden, også når de første mange filer ikke har undertekster. Fejl tælles separat; **Opdater bibliotek** forsøger dem igen.

## Kø og drift

Køen gemmes i `/data/subtitle-translations/jobs.json`. Originalt tekstudtræk og færdige oversættelsesblokke gemmes under jobbets mappe. Genoptagelse oversætter kun manglende blokke. Efter servergenstart skal afbrudte jobs genoptages eksplicit. Annullering stopper ved næste blokgrænse; allerede publicerede sprog bevares. Filer oprettes atomisk uden overskrivning, og publikationskvitteringer gør genforsøg idempotente.

Fremdrift opdateres hvert andet sekund: FFmpeg-tidsposition under udtræk, gennemgåede PGS-data og antal læste undertekster under OCR, færdige tekstblokke under oversættelse, lagring samt verificering i Plex/Fjordflix. Trin uden målelig fremdrift viser en ubestemt aktivitetsbjælke. Samlet procent vægter udtræk 15 %, OCR 20 %, oversættelse 55 % og afslutning 10 %; SRT springer OCR over. Det er arbejdstrin, ikke et tidsestimat. Køoversigten omfatter aktive indsendelser og seneste indsendelse, ikke hele historikken. 100 % kræver vellykket biblioteksopdatering. Ved fejl kan genoptagelse genbruge alle oversatte blokke og gemte SRT-filer.

Underteksternes udtrækning kører i den eksisterende qBittorrent-container med adgang til den valgte biblioteksmappe; OpenAI-kald og credentials ligger i webapp-containeren. Funktionen kræver ikke GPU-konvertering. qBittorrent-containeren skal være startet for at læse biblioteket.

Docker-imaget skal genbygges med de nye moduler, Pillow, PyJWT og Tesseract-sprogpakker. Opdatér også den styrede qBittorrent-container til det nye image via installationens normale opdateringsflow. Der er ingen databaseændring.

Test: `python -m pytest tests/test_subtitle_translation.py tests/test_app.py tests/test_conversion_workflow.py -q` på Linux med FFmpeg. UI-test: `python tests/browser_subtitle_translation.py` med Playwright Chromium. Live OAuth, kontoadgang og oversættelseskvalitet skal verificeres med en rigtig ChatGPT-konto; de automatiske tests bruger syntetiske undertekster og simulerede AI-svar.
