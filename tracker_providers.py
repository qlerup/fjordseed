"""Fixed tracker API destinations and shared capabilities."""
ACCOUNT_REFRESH_SECONDS = 10 * 60

PROVIDERS = {
    'nordicbytes': {'name': 'NordicBytes', 'url': 'https://nordicbytes.org/api/user',
                    'torrents_url': 'https://nordicbytes.org/api/torrents/filter',
                    'hosts': ('nordicbytes.org', 'www.nordicbytes.org')},
    'sagmire': {'name': 'Sagmire', 'url': 'https://sagmire.org/api/user',
                'torrents_url': 'https://sagmire.org/api/torrents/filter',
                'hosts': ('sagmire.org', 'www.sagmire.org')},
}
