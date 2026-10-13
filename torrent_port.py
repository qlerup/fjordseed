"""A second Proton NAT-PMP lease; never modifies the gateway's first port."""
import socket
import logging
import struct
import time

LOG=logging.getLogger(__name__)


def internal_port(gateway_port):
    return 56790 if int(gateway_port)==56789 else 56789


def request(protocol,private,public=0,lifetime=60):
    opcode={'udp':1,'tcp':2}[protocol]
    payload=struct.pack('!BBHHHI',0,opcode,0,private,public,lifetime)
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as client:
        client.settimeout(3)
        client.connect(('10.2.0.1',5351))
        client.send(payload)
        data=client.recv(32)
    if len(data)!=16:
        raise ValueError('Ugyldigt svar fra Protons portvideresendelse.')
    version,operation,result,epoch,assigned_private,assigned_public,seconds=struct.unpack('!BBHIHHI',data)
    if (version!=0 or operation!=opcode+128 or result!=0 or assigned_private!=private
            or seconds!=lifetime or (lifetime and not 1<=assigned_public<=65535)
            or (public and lifetime and assigned_public!=public)):
        raise ValueError('Proton kunne ikke oprette eller forny torrentporten.')
    return assigned_public


class Lease:
    def __init__(self):
        self.private=self.public=self.gateway_port=0
        self.expires=self.next_check=0

    def get(self,gateway_port,now=None):
        started=time.monotonic()
        now=started if now is None else now
        private=internal_port(gateway_port)
        if self.private and (private!=self.private or int(gateway_port)==self.public):
            self.close()
        self.gateway_port=int(gateway_port)
        if self.public and now<self.next_check and now<self.expires:
            return self.private,self.public
        self.private=private;self.gateway_port=int(gateway_port)
        # Keep the private port fixed. Matching UDP/TCP external ports are required
        # for qBittorrent to advertise a single reachable endpoint.
        try:
            udp=request('udp',private,self.public)
            tcp=request('tcp',private,self.public or udp)
        except TimeoutError:
            # A lost renewal reply does not revoke the existing mapping. Only
            # reuse a previously confirmed TCP+UDP lease before its conservative
            # deadline, including time spent waiting for either reply. A partial
            # renewal must never extend that deadline.
            finished=now+max(0,time.monotonic()-started)
            if not self.public or finished>=self.expires:
                raise
            self.next_check=min(finished+2,self.expires)
            LOG.warning('Torrent port renewal timed out; retrying with %.1fs left on confirmed lease',
                        self.expires-finished)
            return self.private,self.public
        if udp!=tcp or tcp in (private,self.gateway_port,8080,9999):
            raise ValueError('Proton gav modstridende torrentporte. Den første gatewayport bevares.')
        self.public=tcp;self.expires=now+50;self.next_check=now+20
        return private,tcp

    def close(self):
        private,public=self.private,self.public
        self.private=self.public=self.gateway_port=0
        self.expires=self.next_check=0
        if private:
            # Cleanup addresses only our explicit non-symmetric private port.
            # A timeout is safe: the provider lease expires within 60 seconds.
            for protocol in ('udp','tcp'):
                try:request(protocol,private,public,0)
                except (OSError,ValueError):pass
