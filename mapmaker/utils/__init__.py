#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020  David Brooks
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
#===============================================================================

import json
import pathlib
import urllib.request

#===============================================================================

def make_url(path):
    if (path.startswith('file:')
     or path.startswith('http:')
     or path.startswith('https:')):
        return path
    return pathlib.Path(path).absolute().as_uri()

#===============================================================================

def open_bytes(path):
    return urllib.request.urlopen(make_url(path))

def read_bytes(path):
    with open_bytes(path) as fp:
        return fp.read()

def read_json(path):
    data = read_bytes(path)
    try:
        return json.loads(data)
    except json.decoder.JSONDecodeError as err:
        raise ValueError('JSON decoder error: {}'.format(err))

#===============================================================================
