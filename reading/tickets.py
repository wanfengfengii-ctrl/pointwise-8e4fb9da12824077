import base64
from dataclasses import dataclass
import hmac
import json
import secrets

from errors import TicketError
from workspace import valid_id


@dataclass(frozen=True, slots=True)
class Ticket:
    volume_id: int
    encoding_id: int
    frame_no: int
    after: int


def initialize_ticket_key(connection):
    connection.execute('''
        CREATE TABLE IF NOT EXISTS ticket_key (
            slot INTEGER PRIMARY KEY CHECK (slot = 1), secret BLOB NOT NULL
        )
    ''')
    if connection.execute('SELECT slot FROM ticket_key WHERE slot = 1').fetchone() is None:
        connection.execute('INSERT INTO ticket_key(slot, secret) VALUES (1, ?)', (secrets.token_bytes(32),))


def get_ticket_key(connection):
    return connection.execute('SELECT secret FROM ticket_key WHERE slot = 1').fetchone()['secret']


def encode_ticket(ticket, key):
    payload = json.dumps([1, ticket.volume_id, ticket.encoding_id, ticket.frame_no, ticket.after],
                         separators=(',', ':')).encode('ascii')
    stamp = hmac.digest(key, payload, 'sha256')
    return base64.urlsafe_b64encode(payload + stamp).decode('ascii')


def parse_ticket(token, key):
    if not isinstance(token, str) or not 1 <= len(token) <= 1024:
        raise TicketError('invalid continuation ticket')
    try:
        raw = base64.b64decode(token, altchars=b'-_', validate=True)
        if len(raw) <= 32 or base64.urlsafe_b64encode(raw).decode('ascii') != token:
            raise ValueError('invalid ticket envelope')
        payload, stamp = raw[:-32], raw[-32:]
        if not hmac.compare_digest(stamp, hmac.digest(key, payload, 'sha256')):
            raise ValueError('invalid ticket signature')
        version, volume, encoding, frame, after = json.loads(payload)
        if type(version) is not int or version != 1 or not valid_id(volume) or not valid_id(encoding):
            raise ValueError('invalid ticket binding')
        if type(frame) is not int or not 0 <= frame < (1 << 63) or not valid_id(after):
            raise ValueError('invalid ticket coordinates')
        return Ticket(volume, encoding, frame, after)
    except (TypeError, ValueError, OverflowError) as exc:
        raise TicketError('invalid continuation ticket') from exc


def validate_ticket_volume(ticket, volume_id):
    if ticket.volume_id != volume_id:
        raise TicketError('continuation ticket belongs to another volume')
