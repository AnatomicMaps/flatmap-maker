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
import sys
import urllib.request

from json.decoder import JSONDecodeError
from urllib.parse import urljoin, urlparse

#===============================================================================

# Export from module

from .logging import ProgressBar, configure_logging, log
from .treelist import TreeList

#===============================================================================

def relative_path(path: str) -> bool:
    return path.split(':', 1)[0] not in ['file', 'http', 'https']

#===============================================================================

class FilePathError(IOError):
    pass

#===============================================================================

class FilePath(object):
    def __init__(self, path: str):
        if relative_path(path):
            self.__url = pathlib.Path(path).absolute().resolve().as_uri()
        else:
            self.__url = path

    @property
    def extension(self):
        parts = self.filename.rsplit('.')
        return parts[-1] if len(parts) > 1 else ''

    @property
    def filename(self):
        return urlparse(self.__url).path.rsplit('/', 1)[-1]

    @property
    def url(self):
        return self.__url

    def __str__(self):
        return str(self.__url)

    def close(self):
        self.__fp.close()

    def get_data(self):
        with self.get_fp() as fp:
            return fp.read()

    def get_fp(self):
        try:
            return urllib.request.urlopen(self.__url)
        except urllib.error.URLError:
            raise FilePathError('Cannot open path: {}'.format(self.__url)) from None

    def get_json(self):
        try:
            return json.loads(self.get_data())
        except json.JSONDecodeError as err:
            raise ValueError('{}: {}'.format(self.__url, err)) from None

    def get_BytesIO(self):
        bytesio = io.BytesIO(self.get_data())
        bytesio.seek(0)
        return bytesio

    def join_path(self, path):
        return FilePath(urljoin(self.__url, path))

    def join_url(self, path):
        return urljoin(self.__url, path)

#===============================================================================
