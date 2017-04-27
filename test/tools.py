# -*- coding: utf-8 -*-

import sys
import collections
import logging
logging.basicConfig(level=logging.DEBUG)

from tornado.ioloop import IOLoop
import datetime
from h2.config import H2Configuration
from h2.connection import H2Connection
import h2.events

log = logging.getLogger('http2_test')

class TestH2Server(object):
    def __init__(
            self,
            on_headers=None,
            on_data=None,
            on_request=None,
            on_stream_end=None,
            wire_delay=0.075
        ):
        self.config = H2Configuration(client_side=False)
        self.conn = H2Connection(config=self.config)
        self.io_stream = None
        self.on_headers = on_headers
        self.on_data = on_data
        self.on_request = on_request
        self.on_stream_end = on_stream_end
        self.wire_delay = wire_delay

        self.headers = {}
        self.bodies = {}

    def connected(self, io_stream):
        self.conn.initiate_connection()
        self.io_stream = io_stream
        self.reply()

    def close(self, code=0, data=None, stream=None):
        self.conn.close_connection(
            error_code=code,
            additional_data=data,
            last_stream_id=stream,
        )
        self.reply()

    def data(self, data):
        events = self.conn.receive_data(data)
        for event in events:
            if isinstance(event, h2.events.RequestReceived):
                self.headers_received(event)
            elif isinstance(event, h2.events.DataReceived):
                self.data_received(event)
            elif isinstance(event, h2.events.StreamEnded):
                self.stream_ended(event)
            elif isinstance(event, h2.events.StreamReset):
                self.stream_ended(event)
            elif isinstance(event, h2.events.RemoteSettingsChanged):
                pass
            elif isinstance(event, h2.events.SettingsAcknowledged):
                pass
            else:
                log.warning('unhandled event in the server %r', event)

        self.reply()

    def headers_received(self, event):
        headers = collections.OrderedDict(event.headers)
        self.headers[ event.stream_id ] = headers
        if self.on_headers:
            self.on_headers(self, event.stream_id, event.headers)

        if event.stream_ended and self.on_request:
            self.on_request(self, event.stream_id, headers)
        if event.stream_ended:
            del self.headers[event.stream_id]

    def data_received(self, event):
        self.bodies.setdefault(event.stream_id, '')
        self.bodies[event.stream_id] += event.data
        if self.on_data:
            self.on_data(self, event.stream_id, event.data)

        if event.stream_ended and self.on_request:
            self.on_request(
                self,
                event.stream_id,
                self.headers[event.stream_id],
                self.bodies[event.stream_id],
            )
        if event.stream_ended:
            del self.headers[event.stream_id]
            del self.bodies[event.stream_id]


    def stream_ended(self, event):
        if self.on_stream_end:
            self.on_stream_end(self, event.stream_id)

    def respond(self, stream, headers, data=None):
        self.conn.send_headers(stream, headers, end_stream=data is None)
        if data is not None:
            self.conn.send_data(stream, data, end_stream=True)

    def reply(self):
        data = self.conn.data_to_send()
        IOLoop.current().call_later(
            self.wire_delay,
            lambda: self.io_stream.data_from_server(data),
        )

class TestIOStream(object):
    def __init__(self, server):
        self.server = server
        self.nodelay = False
        self.close_callback = None
        self.streaming_callback = None
        self.server_data = ''

        self.server.connected(self)

    def set_nodelay(self, value=True):
        self.nodelay = value

    def set_close_callback(self, callback):
        self.close_callback = callback

    def read_until_close(self, streaming_callback=None):
        self.streaming_callback = streaming_callback
        self.data_from_server('')

    def write(self, data):
        IOLoop.current().call_later(0.075, lambda: self.server.data(data) )

    def close(self, exc_info=False):
        log.info("closing, wtF? %s", exc_info)

    def data_from_server(self, data):
        self.server_data += data
        if self.streaming_callback:
            self.streaming_callback(self.server_data)
            self.server_data = ''

class TestTcpClient(object):
    def __init__(self, server, connect_time=0.1, decrease_connect_time=False):
        self.server = server
        self.io_loop = IOLoop.current()
        self.connect_time = connect_time
        self.decrease_connect_time = decrease_connect_time

    def connect(self, host, port, af=None, ssl_options=None,
            max_buffer_size=None, source_ip=None, source_port=None, callback=None):

        def on_connect():
            log.debug('connected')
            callback(TestIOStream(server=self.server))

        self.io_loop.add_timeout( datetime.timedelta( seconds=self.connect_time ), on_connect )
        if self.decrease_connect_time:
            self.connect_time /= 2
