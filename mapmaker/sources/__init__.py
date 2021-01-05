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
EMU_PER_INCH  = 914400

# EPSG:3857 Mercator projection meters
WORLD_METRES_PER_EMU = 0.1   ## This to become a command line parameter...
                             ## Or in a configuration file...

# SVG pixel resolution
PIXELS_PER_INCH = 96
EMU_PER_PIXEL = EMU_PER_INCH/PIXELS_PER_INCH

WORLD_METRES_PER_PIXEL = WORLD_METRES_PER_EMU*EMU_PER_PIXEL

# MBF Bioscience units to EPSG:3857 coordinates
WORLD_METRES_PER_UM = 100

#===============================================================================

# Shapes/pathe with these marked up types and tile layers are excluded when
# image tiling.
EXCLUDE_SHAPE_TYPES = ['group', 'invisible', 'marker', 'path', 'region', 'centreline']
EXCLUDE_TILE_LAYERS = ['pathways']

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
        """
        :returns: The map's (SE, NW) bounds in WGS84 metres.
        :rtype: tuple(float, float, float, float)
        """
        return self.__bounds

    @bounds.setter
    def bounds(self, bounds):
        self.__bounds = bounds

    @property
    def errors(self):
        return self.__errors

    @property
    def extent(self):
        """
        :returns: The map's (SE, NW) bounds as decimal latitude and longitude coordinates.
        :rtype: tuple(float, float, float, float)
        """
        return bounds_to_extent(self.__bounds)

    @property
    def flatmap(self):
        return self.__flatmap

    @property
    def id(self):
        return self.__id

    @property
    def layers(self):
        return self.__layers

    @property
    def raster_source(self):
        return None

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
    def __init__(self, source_kind, source_data, world_transform=None):
        self.__source_kind = source_kind
        self.__source_data = source_data
        self.__world_transform = world_transform

    @property
    def source_data(self):
        return self.__source_data

    @property
    def source_kind(self):
        return self.__source_kind

    @property
    def world_transform(self):
        return self.__world_transform

#===============================================================================

# Export our sources here to avoid circular imports

from .mbfbioscience import MBFSource
from .powerpoint import PowerpointSource
from .svg import SVGSource

#===============================================================================
