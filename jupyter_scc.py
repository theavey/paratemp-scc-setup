#! /usr/bin/env python

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
try:
    import pathlib
except ImportError:
    import pathlib2 as pathlib
import re
import select
import signal
import socket
try:
    import socketserver
except ImportError:
    import SocketServer as socketserver
import subprocess
import sys
import threading
import webbrowser

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
            self.path.parent.mkdir(parents=True, exist_ok=True)
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
        self['server'] = 'scc2.bu.edu'

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

    # TH edit to return this, and not serve forever
    return ForwardServer(("", local_port), SubHander)


#
#
# End of main part taken from paramiko forward.py demo

def ssh_connect():
    _client = paramiko.SSHClient()
    _client.load_system_host_keys()
    password = getpass.getpass("Enter password for {} on {}: ".format(
        config['username'], config['server']))
    log.info("Connecting to ssh host {} ...".format(config['server']))
    try:
        _client.connect(
            config['server'],
            port=22,
            username=config['username'],
            password=password,
        )
    except Exception as e:
        log.fatal("*** Failed to connect to {}: {}".format(config['server'], e))
        sys.exit(1)
    finally:
        del password
    return _client


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--server', default='read_config',
                        help='Which server to use (e.g., scc2.bu.edu). The '
                             'default is to read the setting in the config '
                             'file (which defaults to scc2.bu.edu).')
    parser.add_argument('-u', '--username', default='read_config',
                        help='What username to use for SCC. Default is to '
                             'read config file (which defaults to username on '
                             'this local computer)'
                        )
    parser.add_argument('-l', '--log_level', default=30, type=int,
                        help='Level to write to log (smaller number writes '
                             'more)')
    return parser.parse_args()


class ChannelClosed(Exception):
    pass


def scc_setup(dry=False):
    log.debug('Downloading SCC setup script to ~/.paratemp on SCC')
    scc_script_url = ('https://raw.githubusercontent.com/theavey/'
                      'paratemp-scc-setup/master/prep-for-paratemp.sh')
    client.exec_command('mkdir -p .paratemp')
    _stdout = client.exec_command('wget {} -O {}'.format(scc_script_url,
                                                         scc_script_path))[1]
    _stdout.channel.recv_exit_status()  # wait for it to finish
    _stdout = client.exec_command('chmod +x {}'.format(scc_script_path))[1]
    _stdout.channel.recv_exit_status()  # wait for it to finish
    if dry:
        cl = './{} help'.format(scc_script_path)
    else:
        cl = './{} -i -n'.format(scc_script_path)
    _stdin, _stdout, _stderr = client.exec_command(cl)
    log.debug('paratemp setup script said: {}\nerror message(s): {}'.format(
        _stdout.read(), _stderr.read()))
    config['Setup_on_SCC'] = True


def main():
    global config, client, scc_script_path
    args = parse_args()
    _setup_log(args.log_level)
    config = Config()
    if args.server is not 'read_config':
        config['server'] = args.server
    client = ssh_connect()
    scc_script_path = '.paratemp/prep-for-paratemp.sh'
    if not config['Setup_on_SCC']:
        scc_setup(dry=False)
    log.info('Starting jupyter on {}'.format(config['server']))
    # TODO change directory to ...?
    stdin, stdout, stderr = client.exec_command(
        './{} -s'.format(scc_script_path),
        get_pty=True,  # kills command called on connection close
        timeout=4)
    m = None
    try:
        while not m:
            try:
                log.debug('checking for new stdout...')
                data = stdout.readline()
            except socket.timeout:
                continue
            if data is not None:
                log.debug('stdout: {}'.format(data))
            if len(data) == 0:
                raise ChannelClosed
            data = str(data)
            for line in data.split('\n'):
                m = re.search(r'http(s)?://.*?:(\d+)/(?:\?token=(\w+))?', line)
                if m is not None:
                    break
    except ChannelClosed:
        log.error('Channel closed before finding Jupyter port. '
                  'stdout: {}\nstderr: '
                  '{}'.format(stdout.read(), stderr.read()))
        sys.exit(1)
    except KeyboardInterrupt:
        client.close()
        log.error('KeyboardInterrupt while finding Jupyter port. stderr: '
                  '{}'.format(stderr.read()))
        sys.exit(1)
    log.info('found jupyter server info: port: {}   token: {}'.format(
        m.group(2), m.group(2)))
    https = m.group(1)
    remote_port = int(m.group(2))
    token = m.group(3)
    try:
        log.info("Now forwarding port {} to {}:{}".format(
            11111, config['server'], remote_port))
        tunnel = forward_tunnel(11111, 'localhost', remote_port,
                                client.get_transport())
        thread = threading.Thread(target=tunnel.serve_forever)
        thread.start()
        https = 'http' if https is None else 'https'
        token = '' if token is None else '?token={}'.format(token)
        local_url = '{}://localhost:11111/{}'.format(https, token)
        log.info('local url to access jupyter: {}'.format(local_url))
        # TODO allow browser selection
        webbrowser.open(local_url)
        signal.pause()
    except KeyboardInterrupt:
        log.warning("C-c: Stopping port forwarding.")
        tunnel.shutdown()
        client.close()
        thread.join()
        sys.exit(0)


if __name__ == '__main__':
    main()
