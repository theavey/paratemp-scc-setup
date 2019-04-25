#! /usr/bin/env python3

"""
Setup and run Jupyter (for ParaTemp) on SCC from a local machine


"""

#    Copyright 2019 Thomas Heavey
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

from __future__ import print_function, division

import argparse
import getpass
import json
import logging
import pathlib
import select
import socket
import socketserver
import subprocess
import sys

try:
    import paramiko
except ImportError:
    subprocess.call([sys.executable, "-m", "pip", "install", 'paramiko'])
    import paramiko


log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)


def _setup_log(level=logging.WARNING):
    global handler
    handler = logging.StreamHandler()
    handler.setLevel(level=level)
    formatter = logging.Formatter('%(asctime)s - %(name)s - '
                                  '%(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    log.addHandler(handler)


class Config(dict):

    def __init__(self):
        log.debug('Initializing Config object')
        self.path = pathlib.Path('~/Library/Application '
                                 'Support/ParaTemp/settings.json').expanduser()
        self.temp_path = self.path.with_suffix('.json.new')
        if self.path.is_file():
            log.debug('Reading existing config from {}'.format(self.path))
            d = json.load(self.path.open('r'))
            super(Config, self).__init__(d)
        else:
            log.debug('No existing config found. Creating new')
            super(Config, self).__init__()
            self.setup_config()
            log.info('Wrote new config to {}'.format(self.path))

    def setup_config(self):
        log.debug('Setting up new configuration')
        default_username = getpass.getuser()
        username = input("Username [{}]: ".format(default_username))
        if len(username) == 0:
            username = default_username
        self['username'] = username
        self['Setup_on_SCC'] = False

    def __setitem__(self, key, value):
        try:
            super(Config, self).__setitem__(key, value)
            json.dump(self, self.temp_path.open('w'), indent=4)
            self.temp_path.rename(self.path)
        except Exception:
            log.exception('Exception raised when trying to write config file!')
            raise


# Content for forwarding port mostly taken from paramiko forward.py demo
#
#

class ForwardServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            chan = self.ssh_transport.open_channel(
                "direct-tcpip",
                (self.chain_host, self.chain_port),
                self.request.getpeername(),
            )
        except Exception as e:
            log.error(
                "Incoming request to %s:%d failed: %s"
                % (self.chain_host, self.chain_port, repr(e))
            )
            return
        if chan is None:
            log.error(
                "Incoming request to %s:%d was rejected by the SSH server."
                % (self.chain_host, self.chain_port)
            )
            return

        log.info(
            "Connected!  Tunnel open %r -> %r -> %r"
            % (
                self.request.getpeername(),
                chan.getpeername(),
                (self.chain_host, self.chain_port),
            )
        )
        while True:
            r, w, x = select.select([self.request, chan], [], [])
            if self.request in r:
                data = self.request.recv(1024)
                if len(data) == 0:
                    break
                chan.send(data)
            if chan in r:
                data = chan.recv(1024)
                if len(data) == 0:
                    break
                self.request.send(data)

        peername = self.request.getpeername()
        chan.close()
        self.request.close()
        log.info("Tunnel closed from %r" % (peername,))


def forward_tunnel(local_port, remote_host, remote_port, transport):
    # this is a little convoluted, but lets me configure things for the Handler
    # object.  (SocketServer doesn't give Handlers any way to access the outer
    # server normally.)
    class SubHander(Handler):
        chain_host = remote_host
        chain_port = remote_port
        ssh_transport = transport

    ForwardServer(("", local_port), SubHander).serve_forever()


#
#
# End of taken from paramiko forward.py demo

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-l', '--log_level', default=30,
                        help='Level to write to log (smaller number writes '
                             'more)')
    args = parser.parse_args()
    _setup_log(args.log_level)
