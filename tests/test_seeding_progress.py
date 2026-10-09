from unittest.mock import Mock, patch
from qbit_rpc import execute


def test_status_preserves_seeding_time_and_configured_targets():
    row = {'hash': 'a' * 40, 'ratio': 1, 'ratio_limit': 5,
           'seeding_time': 7200, 'seeding_time_limit': 2880, 'state': 'stalledUP',
           'uploaded': 1073741824}
    def call(path,data=None):
        response = Mock()
        if path == 'app/preferences':
            response.json.return_value = {'current_network_interface': 'tun0', 'upnp': False, 'listen_port': 12345}
        elif path.startswith('torrents/info'):
            response.json.return_value = [row]
        elif path == 'app/version':
            response.text = '5.2.1'
        else:
            response.json.return_value = {}
        return response
    with patch('qbit_rpc.call', side_effect=call):
        torrent = execute('status', {})['torrents'][0]
    for key, value in row.items():
        assert torrent[key] == value
