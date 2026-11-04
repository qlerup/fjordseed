# Opdatering af konverteringen

Server og Windows-program skal opdateres sammen, så jobs bruger samme
konverteringspolitik. Følgende er en udgivelsesprocedure; produktionsopdateringen
udføres først efter godkendelse og efter afslutning eller afbrydelse af aktive
konverteringsjobs. Behold originalfiler og eksisterende konfiguration.

## Kontrol og Windows-pakke

Kør workflowet **PC conversion** på den samlede ændring. **Docker build context**
kontrollerer nu både appens og GPU-konverterens COPY-kilder.

Kør **Windows installer** med version `0.5.7` og `publish=false`. Hent
installationspakken og SHA-256 fra workflowets artifact. Kontrollér installation
oven på den eksisterende version: forbindelsen, mappevalget og Windows-opstart
skal bevares. Afprøv 20/30/40 Mbps og kun lyd med flere sprog og flerkanalslyd;
kontrollér både slutfilen og originalerne. Atmos skal håndteres efter den fælles
konverteringspolitik og må ikke stiltiende miste metadata.

Først når pakken er godkendt, køres workflowet med `publish=true` og et nyt,
ubrugt versionsnummer. FjordSeeds downloadlink henter den seneste udgivelse.
Gem den foregående installer og dens checksum til rollback. Byg altid fra den
samme kontrollerede commit som serveren.

## Server med GPU-service

Brug installationens eksisterende Compose-projektnavn, `.env`, mounts og
Compose-filer. Kommandoerne nedenfor gælder repoets standardfiler; anvender
installationen yderligere overrides, skal de også medtages.

Gem først de kørende images under unikke rollback-tags. Vælg en anden suffix
ved senere opdateringer, og kontrollér, at navnene matcher installationen:

```sh
docker image tag "$(docker container inspect --format '{{.Image}}' fjordseed)" fjordseed-app:before-conversion-057
docker image tag "$(docker container inspect --format '{{.Image}}' fjordseed-converter)" fjordseed-converter:before-conversion-057
docker compose -f docker-compose.yml -f docker-compose.gpu.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.gpu.yml build app converter
```

Efter godkendelse opdateres GPU-skabelonen før appen:

```sh
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --no-build converter
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --no-build app
docker compose -f docker-compose.yml -f docker-compose.gpu.yml ps
```

Appens `converter_runtime.sync` bruger GPU-skabelonens image-ID til at genoprette
den administrerede køworker. Kontrollér appens healthcheck, pc-forbindelsen og
et lille konverteringsjob efter opdateringen. En installation uden GPU-service
bygger/opdaterer kun `app` med dens eksisterende Compose-filer.

## Rollback

Stop eller afslut igangværende jobs før rollback. Opret en midlertidig fil
`compose.conversion-rollback.yml` med de gemte tags:

```yaml
services:
  app:
    image: fjordseed-app:before-conversion-057
  converter:
    image: fjordseed-converter:before-conversion-057
```

Brug den som sidste override, så Compose vælger de gamle images uden at bygge:

```sh
docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f compose.conversion-rollback.yml up -d --no-build converter
docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f compose.conversion-rollback.yml up -d --no-build app
docker compose -f docker-compose.yml -f docker-compose.gpu.yml -f compose.conversion-rollback.yml ps
```

På Windows lukkes programmet helt, og den gemte tidligere installer køres i
samme installationsmappe. Bevar brugerens settings- og preferences-filer.
Nye konverteringsjobs bør først startes igen, når server og pc har kompatible
versioner. Rollback af programkoden gendanner ikke allerede konverterede filer;
originalerne skal fortsat være tilgængelige.
