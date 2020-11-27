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

from mapmaker.geometry import bounds_to_extent

#===============================================================================

# Internal PPT units are EMUs (English Metric Units)
EMU_PER_IN  = 914400

# EPSG:3857 Mercator projection meters
WORLD_METRES_PER_EMU = 0.1   ## This to become a command line parameter...
                             ## Or in a configuration file...

# SVG pixel resolution
PIXELS_PER_IN = 96
EMU_PER_PIXEL = EMU_PER_IN/PIXELS_PER_IN

WORLD_METRES_PER_PIXEL = WORLD_METRES_PER_EMU*EMU_PER_PIXEL

# MBF Bioscience units to EPSG:3857 coordinates
WORLD_METRES_PER_UM = 100

#===============================================================================

class MapSource(object):
    def __init__(self, flatmap, id):
        self.__flatmap = flatmap
        self.__id = id
        self.__errors = []
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
    def extent(self):
        return bounds_to_extent(self.__bounds)

    @property
    def flatmap(self):
        return self.__flatmap

    @property
    def id(self):
        return self.__id

    @property
    def raster_source(self):
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

    def process(self):
    #=================
        raise TypeError('`process()` must be implemented by `MapSource` sub-class')

#===============================================================================

class RasterSource(object):
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

# Export our sources here to avoid circular imports

from .mbfbioscience import MBFSource
from .powerpoint import PowerpointSource

#===============================================================================
