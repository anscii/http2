# -*- coding: utf-8 -*-

import unittest
import sys
import collections
import json
from functools import partial
import logging
logging.basicConfig(level=logging.DEBUG)

import tornado.testing
from tornado.testing import AsyncTestCase
from tornado.ioloop import IOLoop
from http2 import SimpleAsyncHTTP2Client
import datetime
from h2.config import H2Configuration
from h2.connection import H2Connection
from h2.events import *

from tools import TestH2Server, TestIOStream, TestTcpClient

log = logging.getLogger('http2_test_client')


class BasicTest(AsyncTestCase):

    def setUp(self):
        self.server = None
        self.client = None
        self.msg_count = 0
        self.io_loop = IOLoop.current()
        self.streams = {}

    def _callback(self, response, code=200):
        log.debug(response)
        self.msg_count += 1

        self.assertIsNotNone(response)
        self.assertEqual(code, response.code)
        if self.msg_count == len(self.streams):
            self.stop()


    def init_client(self):
        self.client = SimpleAsyncHTTP2Client(
            self.io_loop, host='localhost',
            tcp_client=TestTcpClient(server=self.server),
            force_instance=True
        )
        self.assertIsNotNone(self.client)


    def on_headers(self, server, stream_id, headers):
        self.assertTrue(stream_id > 0)
        self.streams[stream_id] = False
        resp_headers = (
            (':status', '200'),
        )
        server.respond(stream_id, resp_headers)

    def on_request(self, server, stream_id, headers, data=None, stop_on=None):
        self.assertTrue(stream_id > 0)
        self.streams[stream_id] = False

        if stop_on and len(self.streams) == stop_on:
            server.close(666, 'WTF', stream_id)
        else:
            resp_headers = (
                (':status', '200'),
            )
            server.respond(stream_id, resp_headers)

    def on_stream_end(self, server, stream_id):
        self.assertTrue(stream_id > 0)
        self.streams[stream_id] = True

        if self.msg_count == len(self.streams):
            for stream_ended in self.streams.values():
                self.assertTrue(stream_ended, msg='stream was closed by the client')

            self.stop()

    def test_single_get_request(self):
        self.server = TestH2Server(
            on_request=self.on_request,
            on_stream_end=self.on_stream_end
        )
        self.init_client()

        self.client.fetch('/', raise_error=False, callback=self._callback)
        self.wait() 

    def test_server_responding_before_whole_request(self):

        self.server = TestH2Server(
            on_headers=self.on_headers,
            on_stream_end=self.on_stream_end
        )
        self.init_client()

        self.client.fetch('/', method='POST', body='x'*100000, raise_error=False, callback=self._callback)
        self.wait()

    def test_several_requests(self):
        self.server = TestH2Server(
            on_request=self.on_request,
            on_stream_end=self.on_stream_end
        )
        self.init_client()
        num = 10

        for x in xrange(num):
            self.client.fetch('/?%s' % x, raise_error=False, callback=self._callback)

        self.wait()
        self.assertEqual(len(self.streams), num)

    def test_err_request(self):
        num = 5
        stop_on = 2

        self.server = TestH2Server(
            on_request=partial(self.on_request, stop_on=stop_on),
            on_stream_end=self.on_stream_end
        )
        self.init_client()

        for x in xrange(1, num+1):
            if x >= stop_on:
                cb = partial(self._callback, code=418)
            else:
                cb = self._callback

            # self.client.fetch('/?%s' % x, raise_error=False, callback=cb)
            self.client.fetch('/', method='POST', body='x'*1000*x, raise_error=False, callback=cb)

        self.wait(timeout=30)
        self.assertEqual(self.msg_count, num)

if __name__ == '__main__':
    unittest.main()
