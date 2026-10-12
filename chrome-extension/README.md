# FjordSeed til Chrome

1. Pak ZIP-filen ud i en mappe, du beholder på computeren.
2. Åbn `chrome://extensions`, slå **Udviklertilstand** til og vælg **Indlæs udpakket**.
3. Vælg mappen med `manifest.json`.
4. Åbn udvidelsen i Chromes værktøjslinje. Gem din FjordSeed-adresse, fx `https://seed.example.dk` eller `http://192.168.1.110:8099`, og tillad adgang til den adresse.
5. Log ind på NordicBytes i Chrome. Højreklik på torrentens downloadlink og vælg **Send til FjordSeed**.
6. Udvidelsen aktiverer en eksisterende FjordSeed-fane og dens vindue. Hvis ingen findes, åbner den en ny. Log ind om nødvendigt. Vælg behold/slet og seeding i den normale dialog og tryk **Start download**. En åben dialog bliver ikke overskrevet; luk den og vælg **Fortsæt** i udvidelsen.

Udvidelsen henter kun den lille .torrent-fil via dit eksisterende NordicBytes-login. Den gemmer ingen fil i Chromes downloadmappe. Selve indholdet downloades først af FjordSeed efter din godkendelse, med de eksisterende regler for VPN, buffer og seeding.

Højreklikspunktet gælder kun `https://nordicbytes.org/torrents/download/<nummer>` (og eventuelle query-parametre). Chromes almindelige “Kopiér linkadresse” påvirkes ikke. Udvidelsen læser ikke udklipsholderen.

## Hvis noget ikke virker

Klik på udvidelsens ikon for status. En ventende torrent kan fortsættes eller ryddes. Luk andre åbne dialoger i FjordSeed og kontrollér VPN-status, hvis du bliver bedt om det. Kun én torrent kan vente ad gangen. Den afvises efter 15 minutter og ligger kun i browserens sessionshukommelse, indtil den er afleveret eller browseren lukkes. Efter aflevering styres dialogen af FjordSeed; rydning i udvidelsen annullerer ikke en allerede startet download.

Login-omdirigeringer eller fejl fra NordicBytes sendes ikke til FjordSeed som torrentfiler. Ved fejl: log ind på NordicBytes og send linket igen. FjordSeeds adresse skal være grundadressen uden `/login` eller undermapper.

## Adgang og opdatering

Udvidelsen får adgang til NordicBytes og kun den FjordSeed-server, du giver tilladelse til. Den læser ikke cookies via cookie-API'et og gemmer ingen adgangskoder eller API-nøgler. Chrome-hosttilladelser gælder alle porte på den valgte vært; overførsel kontrollerer også den præcise port. Ingen eksterne analyseværktøjer eller scripts bruges.

Denne version installeres manuelt og er ikke udgivet i Chrome Web Store. Ved en ny version erstattes filerne i udvidelsens mappe, og der trykkes **Genindlæs** på `chrome://extensions`.
