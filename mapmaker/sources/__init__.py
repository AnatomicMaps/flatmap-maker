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

import cv2
import numpy as np

#===============================================================================

from mapmaker.geometry import bounds_to_extent

from .markup import parse_markup

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

# Shapes/path with these marked up types and tile layers are excluded when
# image tiling.
EXCLUDE_SHAPE_TYPES = ['group', 'invisible', 'marker', 'path', 'region', 'centreline']
EXCLUDE_TILE_LAYERS = ['pathways']

#===============================================================================

WHITE     = (255, 255, 255)

#===============================================================================

# Based on https://stackoverflow.com/a/54148416/2159023

def add_alpha(image, colour=WHITE):
#==================================
    transparent = image.copy()
    if colour == WHITE:
        transparent[:, :, 3] = (255*((transparent[:, :, :3] != 255).any(axis=2) * (transparent[:, :, 3] != 0))).astype(np.uint8)
    else:
        transparent[:, :, 3] = (255*((transparent[:,:,0:3] != tuple(colour)[0:3]).any(axis=2) * (transparent[:, :, 3] != 0))).astype(np.uint8)
    return transparent

def blank_image(size=(1, 1)):
#============================
    tile = np.full(size + (4,), 255, dtype=np.uint8)
    tile[:,:,3] = 0
    return tile

def mask_image(image, mask_polygon):
#===================================
    mask = np.full(image.shape, 255, dtype=np.uint8)
    if image.shape[2] == 4:
        mask[:, :, 3] = 0
    mask_color = (0,)*image.shape[2]
    cv2.fillPoly(mask, np.array([mask_polygon.exterior.coords], dtype=np.int32),
                 color=mask_color, lineType=cv2.LINE_AA)
    return cv2.bitwise_or(image, mask)

def not_empty(image):
#====================
    return np.any(image[:,:,3])

#===============================================================================

class MapSource(object):
    def __init__(self, flatmap, id, kind):
        self.__flatmap = flatmap
        self.__id = id
        self.__kind = kind
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
    def kind(self):
        return self.__kind

    @property
    def layers(self):
        return self.__layers

    @property
    def raster_source(self):
        return None

    def add_layer(self, layer):
    #==========================
        self.__layers.append(layer)

    def error(self, kind, msg):
    #==========================
        self.__errors.append((kind, msg))

    def map_area(self):
    #==================
        return abs(self.__bounds[2] - self.__bounds[0]) * (self.__bounds[3] - self.__bounds[1])

    def properties_from_markup(self, markup):
    #========================================
        if not markup.startswith('.'):
            return {}
        properties = parse_markup(markup)
        if 'error' in properties:
            self.error('error', '{}: {} in markup: {}'
                       .format(self.id, properties['error'], markup))
        if 'warning' in properties:
            self.error('warning', '{}: {} in markup: {}'
                       .format(self.id, properties['warning'], markup))
        for key in ['id', 'path']:
            if key in properties:
                if self.__flatmap.is_duplicate_feature_id(properties[key]):
                   self.error('error', '{}: duplicate id in markup: {}'
                              .format(self.id, markup))
        return properties

    def process(self):
    #=================
        raise TypeError('`process()` must be implemented by `MapSource` sub-class')

#===============================================================================

class RasterSource(object):
    def __init__(self, source_kind, source_data, **kwds):
        self.__source_kind = source_kind
        self.__source_data = source_data
        self.__source_params = kwds

    @property
    def source_data(self):
        return self.__source_data

    @property
    def source_kind(self):
        return self.__source_kind

    @property
    def source_params(self):
        return self.__source_params

#===============================================================================

# Export our sources here to avoid circular imports

from .mbfbioscience import MBFSource
from .powerpoint import PowerpointSource
from .svg import SVGSource

#===============================================================================
