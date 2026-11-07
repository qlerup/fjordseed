# Buffer og beholdte filer

Under **Lager og mapper** vises både bufferens placering og den valgte mappe til beholdte filer. Funktionen kan bruges med eller uden Fjordflix.

1. Vælg **Storagepools og tilslutning** for at se de Proxmox-lagre, FjordHub har adgang til.
2. Et tilgængeligt lager åbner mappevælgeren. Vælg en eksisterende mappe, eller brug **Opret mappe**.
3. Et lager uden skriveadgang til FjordHubs LXC får en **Tilslut storagepool til Fjordseed**-guide. Kopiér kommandoen og kør den i Proxmox Shell. Den bruger kun det valgte, allerede monterede filsystem og opretter et bind mount; den formaterer ikke disken og flytter ingen eksisterende medier. Proxmox kan aktivere mountet med det samme. Hvis ikke, viser kommandoen den nødvendige LXC-genstart.
4. Genindlæs oversigten og vælg mappen til beholdte filer.

På nye installationer bevarer `/downloads` sin rolle som bufferdisk. Docker Compose indstiller værtsmappen med `DOWNLOADS_DIR`. Nye buffered downloads starter i `/downloads/.incomplete`, uanset destinationen til beholdte filer. Kun færdige downloads, som skal beholdes, flyttes med qBittorrents `setLocation` til den valgte destination. Seeding fortsætter fra den nye placering. Seeder og Originals bliver også på download-disken.

Valget gælder nye manuelle downloads og RSS. Hvert download gemmer sin buffer og destination ved oprettelsen. Et senere mappeskift flytter ikke eksisterende torrents eller gamle filer. Gamle konfigurationer uden `buffer_path` læses fortsat; allerede oprettede records ændres ikke.

Fjordflix og Plex skal kunne læse den valgte destination. Et nyt mappevalg i Fjordseed ændrer ikke automatisk deres biblioteker. Tilslut mappen i Fjordflix og Plex, eller bevar en eksisterende intern bibliotekssti gennem et bind mount ved en administreret diskflytning.

Proxmox-guiden kræver en FjordHub-forbindelse med lageroversigt og en FjordHub-administrator. På en selvstændig Docker-installation monteres disken først på Docker-værten; derefter vælges mappen under `/mnt`, `/media` eller `/srv`. Fjordseed kontrollerer mount og skriveadgang, før valget gemmes. Guiden opretter kun en ny appmappe med de korrekte UID/GID og ændrer ikke ejerskab på eksisterende filer. Brugerdefinerede LXC UID-maps kræver manuel opsætning.
