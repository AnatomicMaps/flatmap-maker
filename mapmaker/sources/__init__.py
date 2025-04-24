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

from typing import Callable, Optional, TYPE_CHECKING

#===============================================================================

import cv2
import numpy as np

#===============================================================================

from mapmaker.geometry import bounds_to_extent, MapBounds, Transform
from mapmaker.flatmap import SourceBackground, SourceManifest, SOURCE_DETAIL_KINDS
from mapmaker.flatmap.layers import MapLayer, PATHWAYS_TILE_LAYER
from mapmaker.properties.markup import parse_markup
from mapmaker.shapes import Shape
from mapmaker.utils import FilePath

if TYPE_CHECKING:
    from mapmaker.flatmap import FlatMap

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
EMU_PER_METRE = 1.0/WORLD_METRES_PER_EMU

POINTS_PER_PIXEL = POINTS_PER_INCH/PIXELS_PER_INCH

WORLD_METRES_PER_PIXEL = WORLD_METRES_PER_EMU*EMU_PER_PIXEL

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
    def __init__(self, flatmap: 'FlatMap', source_manifest: SourceManifest):
        self.__flatmap = flatmap
        self.__id = source_manifest.id
        self.__href = source_manifest.href
        self.__kind = source_manifest.kind
        self.__source_range = source_manifest.source_range
        self.__errors: list[tuple[str, str]] = []
        self.__layers: list[MapLayer] = []
        self.__bounds: MapBounds = (0, 0, 0, 0)
        self.__raster_sources = None
        self.__background_raster_source = source_manifest.background_source
        self.__zoom_point_id = None
        if self.__kind in SOURCE_DETAIL_KINDS:
            if source_manifest.feature is None:
                raise ValueError('A `detail` source must specify an existing `feature`')
            if source_manifest.zoom < 1:
                raise ValueError('A `detail` source must specify `zoom`')
            if (feature := flatmap.get_feature(source_manifest.feature)) is None:
                raise ValueError(f'Unknown source feature: {source_manifest.feature}')
            feature.set_property('maxzoom', source_manifest.zoom-1)
            if source_manifest.kind == 'functional':
                details_for = source_manifest.details if source_manifest.details is not None else source_manifest.feature
                if (detail_feature := flatmap.get_feature(details_for)) is None:
                    raise ValueError(f'Unknown source feature: {details_for}')
                self.__zoom_point_id = flatmap.add_details_layer(detail_feature, self.id, source_manifest.description)
            self.__min_zoom = source_manifest.zoom
            self.__base_feature = feature
        else:
            self.__min_zoom = flatmap.min_zoom
            self.__base_feature = None
        self.__feature_alignment = source_manifest.alignment

    @property
    def annotator(self):
        return None

    @property
    def background_raster_source(self) -> Optional[SourceBackground]:
        return self.__background_raster_source

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
    def layers(self) -> list[MapLayer]:
        return self.__layers

    @property
    def max_zoom(self):
        return self.__flatmap.max_zoom

    @property
    def min_zoom(self):
        return self.__min_zoom

    @property
    def raster_sources(self) -> list['RasterSource']:
        if self.__raster_sources is None:
            self.__raster_sources = self.get_raster_sources()
        return self.__raster_sources     # type: ignore

    @property
    def href(self):
        return self.__href

    @property
    def source_range(self) -> Optional[list[int]]:
        return self.__source_range

    @property
    def transform(self) -> Optional[Transform]:
        return None

    @property
    def zoom_point_id(self):
        return self.__zoom_point_id

    def add_layer(self, layer: MapLayer):
    #====================================
        layer.create_feature_groups()
        if len(self.__feature_alignment):
            layer.align_layer(self.__feature_alignment)
        self.__layers.append(layer)

    def create_preview(self):
    #========================
        pass

    def error(self, kind: str, msg: str):
    #====================================
        self.__errors.append((kind, msg))

    def filter_map_shape(self, shape: Shape):
    #========================================
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

    def get_raster_sources(self) -> list['RasterSource']:
    #====================================================
        return []

#===============================================================================

class RasterSource(object):
    def __init__(self, id: str, kind: str, get_data: Callable[[], bytes],
                 map_source: MapSource, source_path: Optional[FilePath]=None,
                 background_layer: bool=False, transform: Optional[Transform]=None):
        self.__id = id
        self.__kind = kind
        self.__get_data = get_data
        self.__data = None
        self.__map_source = map_source
        self.__source_path = source_path
        self.__background_layer = background_layer
        self.__transform = transform

    @property
    def background_layer(self):
        return self.__background_layer

    @property
    def data(self) -> bytes:
        if self.__data is None:
            self.__data = self.__get_data()
        return self.__data

    @property
    def id(self) -> str:
        return self.__id

    @property
    def kind(self) -> str:
        return self.__kind

    @property
    def map_source(self):
        return self.__map_source

    @property
    def source_path(self) -> Optional[FilePath]:
        return self.__source_path

    @property
    def transform(self) -> Optional[Transform]:
        return self.__transform

#===============================================================================

# Export our sources here to avoid circular imports

from .fc_powerpoint import FCPowerpointSource
from .mbfbioscience import MBFSource
from .powerpoint import PowerpointSource
from .svg import SVGSource

#===============================================================================
