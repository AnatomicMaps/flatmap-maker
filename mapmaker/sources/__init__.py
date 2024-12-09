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

from io import BytesIO
from typing import Callable, Optional, TYPE_CHECKING

#===============================================================================

import cv2
import numpy as np

#===============================================================================

from mapmaker.geometry import bounds_to_extent, Transform
from mapmaker.flatmap import ManifestSource
from mapmaker.flatmap.layers import PATHWAYS_TILE_LAYER
from mapmaker.properties.markup import parse_markup
from mapmaker.utils import FilePath

if TYPE_CHECKING:
    from mapmaker.flatmap import FlatMap, MapLayer

#===============================================================================

MapBounds = tuple[float, float, float, float]

#===============================================================================

POINTS_PER_INCH = 72

# Internal PPT units are EMUs (English Metric Units)
EMU_PER_INCH = 914400

# EPSG:3857 Mercator projection meters
WORLD_METRES_PER_EMU = 0.1   ## This to become a command line parameter...
                             ## Or in a configuration file...

# SVG pixel resolution
PIXELS_PER_INCH = 96
EMU_PER_PIXEL = EMU_PER_INCH/PIXELS_PER_INCH
EMU_PER_POINT = EMU_PER_INCH/POINTS_PER_INCH
EMU_PER_METRE = 1.0/WORLD_METRES_PER_EMU

POINTS_PER_PIXEL = POINTS_PER_INCH/PIXELS_PER_INCH

WORLD_METRES_PER_PIXEL = WORLD_METRES_PER_EMU*EMU_PER_PIXEL
WORLD_METRES_PER_POINT = WORLD_METRES_PER_EMU*EMU_PER_POINT

# MBF Bioscience units to EPSG:3857 coordinates
WORLD_METRES_PER_UM = 100

#===============================================================================

# Shapes/paths with these types are excluded from image tiling
EXCLUDE_SHAPE_TYPES = [
    'centreline',
    'group',
    'invisible',  ## Maybe have an ``id`` or ``class`` ==> not invisible...
    'marker',
    'node',
    'path',
    'region',
    ]

# Shapes/paths in these layers are excluded from image tiling
EXCLUDE_TILE_LAYERS = [
    PATHWAYS_TILE_LAYER      # All paths are in vector layers
]

# Features that have a `type` attribute in this list are excluded from image
# tiling
EXCLUDED_FEATURE_TYPES = [
    'nerve'         # Nerve cuffs are in vector layers
]

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
    def __init__(self, flatmap: 'FlatMap', manifest_source: ManifestSource):
        self.__flatmap = flatmap
        self.__id = manifest_source.id
        self.__href = manifest_source.href
        self.__kind = manifest_source.kind
        self.__source_range = manifest_source.source_range
        self.__errors: list[tuple[str, str]] = []
        self.__layers: list['MapLayer'] = []
        self.__bounds: MapBounds = (0, 0, 0, 0)
        self.__raster_source = None
        if self.__kind == 'detail':
            if manifest_source.feature is None:
                raise ValueError('A `detail` source must specify an existing `feature`')
            if manifest_source.zoom < 1:
                raise ValueError('A `detail` source must specify `zoom`')
            if ((feature := flatmap.get_feature_by_name(manifest_source.feature)) is None
            and (feature := flatmap.get_feature(manifest_source.feature)) is None):
                raise ValueError(f'Unknown source feature: {manifest_source.feature}')
            feature.set_property('maxzoom', manifest_source.zoom-1)
            feature.set_property('kind', 'expandable')
            self.__min_zoom = manifest_source.zoom
            self.__base_feature = feature
        else:
            self.__min_zoom = flatmap.min_zoom
            self.__base_feature = None

    @property
    def annotator(self):
        return None

    @property
    def base_feature(self):
        return self.__base_feature

    @property
    def bounds(self) -> MapBounds:
        """
        :returns: The map's (SE, NW) bounds in WGS84 metres.
        :rtype: tuple(float, float, float, float)
        """
        return self.__bounds

    @bounds.setter
    def bounds(self, bounds: MapBounds):
        self.__bounds = bounds

    @property
    def errors(self) -> list[tuple[str, str]]:
        return self.__errors

    @property
    def extent(self) -> MapBounds:
        """
        :returns: The map's (SE, NW) bounds as decimal latitude and longitude coordinates.
        :rtype: tuple(float, float, float, float)
        """
        return bounds_to_extent(self.__bounds)

    @property
    def flatmap(self) -> 'FlatMap':
        return self.__flatmap

    @property
    def id(self) -> str:
        return self.__id

    @property
    def kind(self) -> str:
        return self.__kind

    @property
    def layers(self) -> list['MapLayer']:
        return self.__layers

    @property
    def max_zoom(self):
        return self.__flatmap.max_zoom

    @property
    def min_zoom(self):
        return self.__min_zoom

    @property
    def raster_source(self) -> 'RasterSource':
        if self.__raster_source is None:
            self.__raster_source = self.get_raster_source()
        return self.__raster_source     # type: ignore

    @property
    def href(self):
        return self.__href

    @property
    def source_range(self) -> Optional[list[int]]:
        return self.__source_range

    @property
    def transform(self) -> Optional[Transform]:
        return None

    def add_layer(self, layer: 'MapLayer'):
    #======================================
        self.__layers.append(layer)

    def create_preview(self):
    #========================
        pass

    def error(self, kind: str, msg: str):
    #====================================
        self.__errors.append((kind, msg))

    def filter_map_shape(self, shape):
    #=================================
        return

    def map_area(self) -> float:
    #===========================
        return abs(self.__bounds[2] - self.__bounds[0]) * (self.__bounds[3] - self.__bounds[1])

    def properties_from_markup(self, markup: str) -> dict:
    #=====================================================
        if not markup.startswith('.'):
            return {}
        properties = parse_markup(markup)
        self.check_markup_errors(properties)
        self.__flatmap.properties_store.update_properties(properties)
        return properties

    def check_markup_errors(self, properties: dict):
    #===============================================
        if properties.get('markup', '') != '':
            if 'error' in properties:
                self.error('error', '{}: {} in markup: {}'
                           .format(self.id, properties['error'], properties.get('markup', '')))
            if 'warning' in properties:
                self.error('warning', '{}: {} in markup: {}'
                           .format(self.id, properties['warning'], properties.get('markup', '')))
            for key in ['id', 'path']:
                if key in properties:
                    if self.__flatmap.duplicate_feature_id(properties[key]):
                       self.error('error', '{}: duplicate id in markup: {}'
                              .format(self.id, properties.get('markup', '')))

    def process(self) -> None:
    #=========================
        raise TypeError('`process()` must be implemented by `MapSource` sub-class')

    def get_raster_source(self) -> Optional['RasterSource']:
    #=======================================================
        return None

#===============================================================================

class RasterSource(object):
    def __init__(self, kind: str, get_data: Callable[[], bytes], source_path: Optional[FilePath]=None):
        self.__kind = kind
        self.__get_data = get_data
        self.__data = None
        self.__source_path = source_path

    @property
    def data(self) -> bytes:
        if self.__data is None:
            self.__data = self.__get_data()
        return self.__data

    @property
    def kind(self) -> str:
        return self.__kind

    @property
    def source_path(self) -> Optional[FilePath]:
        return self.__source_path

#===============================================================================

# Export our sources here to avoid circular imports

from .fc_powerpoint import FCPowerpointSource
from .mbfbioscience import MBFSource
from .powerpoint import PowerpointSource
from .svg import SVGSource

#===============================================================================
