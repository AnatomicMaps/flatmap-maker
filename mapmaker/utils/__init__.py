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

import io
import json
import pathlib
import urllib.request

#===============================================================================

# Export from module

from .logging import ProgressBar, log

#===============================================================================

def make_url(path):
    if (path.startswith('file:')
     or path.startswith('http:')
     or path.startswith('https:')):
        return path
    return pathlib.Path(path).absolute().as_uri()

#===============================================================================

def path_open(path):
    return urllib.request.urlopen(make_url(path))

def path_BytesIO(path):  # Return seekable file
    bytesio = io.BytesIO(path_data(path))
    bytesio.seek(0)
    return bytesio

def path_data(path):
    with path_open(path) as fp:
        return fp.read()

def path_json(path):
    data = path_data(path)
    try:
        return json.loads(data)
    except json.decoder.JSONDecodeError as err:
        raise ValueError('JSON decoder error: {}'.format(err))

#===============================================================================
