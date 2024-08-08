#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020 - 2023 David Brooks
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
import os
import pathlib
from typing import Any
import urllib.error
from urllib.parse import urljoin, urlparse
import urllib.request

#===============================================================================

# Export from module

from .logging import ProgressBar, configure_logging, log
from .property_mixin import PropertyMixin
from .treelist import TreeList

#===============================================================================

def relative_path(path: str | pathlib.Path) -> bool:
    return str(path).split(':', 1)[0] not in ['file', 'http', 'https']

def make_uri(path: str | pathlib.Path) -> str:
    return pathlib.Path(os.path.abspath(path)).as_uri() if relative_path(path) else str(path)

def pathlib_path(path: str) -> pathlib.Path:
    return pathlib.Path(urlparse(path).path)

#===============================================================================

# Output sets as JSON lists
def set_as_list(s):
    return list(s) if isinstance(s, set) else s

#===============================================================================

class FilePathError(IOError):
    pass

#===============================================================================

class FilePath(object):
    def __init__(self, path: str):
        self.__url = make_uri(path)

    @property
    def extension(self) -> str:
        parts = self.filename.rsplit('.')
        return parts[-1] if len(parts) > 1 else ''

    @property
    def filename(self) -> str:
        return urlparse(self.__url).path.rsplit('/', 1)[-1]

    @property
    def url(self) -> str:
        return self.__url

    def __str__(self) -> str:
        return self.__url

    def get_data(self):
        with self.get_fp() as fp:
            return fp.read()

    def get_fp(self):
        try:
            return urllib.request.urlopen(self.__url)
        except urllib.error.URLError:
            raise FilePathError('Cannot open path: {}'.format(self.__url)) from None

    def get_json(self) -> Any:
        try:
            return json.loads(self.get_data())
        except json.JSONDecodeError as err:
            raise ValueError('{}: {}'.format(self.__url, err)) from None

    def get_BytesIO(self) -> io.BytesIO:
        bytesio = io.BytesIO(self.get_data())
        bytesio.seek(0)
        return bytesio

    def join_path(self, path: str) -> FilePath:
        return FilePath(urljoin(self.__url, path))

    def join_url(self, path: str) -> str:
        return urljoin(self.__url, path)

#===============================================================================
