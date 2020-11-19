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

from mapmaker.geometry import mercator_transformer

#===============================================================================

class MapSource(object):
    def __init__(self, flatmap, id, source_path):
        self.__flatmap = flatmap
        self.__id = id
        self.__errors = []
        self.__path = source_path
        self.__layers = []
        self.__bounds = (0, 0, 0, 0)

    @property
    def bounds(self):
        return self.__bounds

    @bounds.setter
    def bounds(self, bounds):
        self.__bounds = bounds

    @property
    def errors(self):
        return self.__errors

    @property
    def flatmap(self):
        return self.__flatmap

    @property
    def id(self):
        return self.__id

    @property
    def image_tile_source(self):
        return None

    @property
    def layers(self):
        return self.__layers

    def add_layer(self, layer):
    #==========================
        self.__layers.append(layer)

    def error(self, msg):
    #====================
        self.__errors.append(msg)

    def map_area(self):
    #==================
        return abs(self.__bounds[2] - self.__bounds[0]) * (self.__bounds[3] - self.__bounds[1])

    def extent(self):
    #================
        bounds = self.__bounds
        sw = mercator_transformer.transform(self.__bounds[0], self.__bounds[1])
        ne = mercator_transformer.transform(self.__bounds[2], self.__bounds[3])
        return (sw[0], sw[1], ne[0], ne[1])

    def process(self):
    #=================
        raise TypeError('`process()` must be implemented by `MapSource` sub-class')

#===============================================================================

class ImageTileSource(object):
    def __init__(self, source_kind, source_bytes):
        self.__source_kind = source_kind
        self.__source_bytes = source_bytes

    @property
    def source_bytes(self):
        return self.__source_bytes

    @property
    def source_kind(self):
        return self.__source_kind

#===============================================================================
