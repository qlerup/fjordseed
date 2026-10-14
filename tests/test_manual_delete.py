from unittest.mock import Mock

import pytest

import qbit_rpc
from test_app import app, login


@pytest.mark.parametrize('choice', [False, True])
def test_delete_choice_reaches_worker(app, choice):
    client, headers = login(app)
    app.extensions['state'].save('a'*32, True)
    response = client.post('/api/torrents/'+'a'*40+'/delete', headers=headers,
                           json={'delete_files':choice, 'confirm_early_stop':True})
    assert response.status_code == 200
    app.extensions['runtime'].rpc.assert_called_once_with('delete', {
        'hash':'a'*40, 'delete_files':choice, 'confirm_early_stop':True})


@pytest.mark.parametrize('choice', ['false', 'true', 0, 1, None, []])
def test_delete_rejects_non_boolean_choice(app, choice):
    client, headers = login(app)
    app.extensions['state'].save('a'*32, True)
    assert client.post('/api/torrents/'+'a'*40+'/delete', headers=headers,
                       json={'delete_files':choice}).status_code == 400
    app.extensions['runtime'].rpc.assert_not_called()


@pytest.mark.parametrize('data,expected', [({}, 'false'), ({'delete_files':False}, 'false'),
                                          ({'delete_files':True}, 'true')])
def test_rpc_file_deletion_requires_explicit_choice(monkeypatch, data, expected):
    rpc = Mock(side_effect=lambda path, data=None: Mock(json=lambda:
        {'current_network_interface':'tun0', 'upnp':False} if path=='app/preferences'
        else [{'hash':'a'*40, 'ratio':1, 'seeding_time':0}]))
    monkeypatch.setattr(qbit_rpc, 'call', rpc)
    qbit_rpc.execute('delete', {'hash':'a'*40, **data})
    assert rpc.call_args.args == ('torrents/delete', {'hashes':'a'*40, 'deleteFiles':expected})


def test_file_deletion_still_requires_early_stop_confirmation(monkeypatch):
    rpc = Mock(side_effect=lambda path, data=None: Mock(json=lambda:
        {'current_network_interface':'tun0', 'upnp':False} if path=='app/preferences'
        else [{'hash':'a'*40, 'ratio':0, 'seeding_time':0}]))
    monkeypatch.setattr(qbit_rpc, 'call', rpc)
    with pytest.raises(qbit_rpc.SeedingRequirementError):
        qbit_rpc.execute('delete', {'hash':'a'*40, 'delete_files':True})
    assert not any(c.args[0]=='torrents/delete' for c in rpc.call_args_list)
