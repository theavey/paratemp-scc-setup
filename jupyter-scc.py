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

import getpass
import json
import logging
import pathlib
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


if __name__ == '__main__':
    _setup_log()
