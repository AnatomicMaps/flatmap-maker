#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2024  David Brooks
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

from typing import TYPE_CHECKING, Optional

#===============================================================================

import shapely
from shapely.geometry.base import BaseGeometry
import shapely.ops
import shapely.prepared

#===============================================================================

from mapmaker import MIN_ZOOM
from mapmaker.exceptions import GroupValueError
from mapmaker.geometry import connect_dividers, extend_line, make_boundary
from mapmaker.geometry import save_geometry
from mapmaker.settings import settings
from mapmaker.utils import log

if TYPE_CHECKING:
    from mapmaker.sources import MapSource
    from . import FlatMap

from .feature import Feature

#===============================================================================

FEATURES_TILE_LAYER = 'features'
PATHWAYS_TILE_LAYER = 'pathways'

#===============================================================================

class FeatureLayer(object):
    def __init__(self, id: str, flatmap: 'FlatMap', exported: bool=False):
        self.__id = id
        self.__flatmap = flatmap
        self.__annotations = {}
        self.__exported = exported
        self.__description = f'{id} layer'.capitalize()
        self.__features: list[Feature] = []

    @property
    def annotations(self) -> dict:
        return self.__annotations

    @property
    def exported(self) -> bool:
        return self.__exported

    @property
    def description(self) -> str:
        return self.__description

    @description.setter
    def description(self, value: str):
        self.__description = value

    @property
    def detail_layer(self) -> bool:
        return False

    @property
    def features(self) -> list[Feature]:
        return self.__features

    @property
    def flatmap(self) -> 'FlatMap':
        return self.__flatmap

    @property
    def id(self) -> str:
        return self.__id

    @property
    def max_zoom(self) -> Optional[int]:
        return None

    @property
    def min_zoom(self) -> Optional[int]:
        return None

    @property
    def raster_layers(self) -> list['RasterLayer']:
        return []

    def add_feature(self, feature: Feature, map_layer: Optional['MapLayer']=None):
    #=============================================================================
        feature.layer = map_layer
        if (not settings.get('onlyNetworks', False) or self.__flatmap.network_feature(feature)):
            self.__features.append(feature)

    def annotate(self, feature: Feature, properties: dict):
    #======================================================
        self.__annotations[feature.geojson_id] = properties

    def set_feature_properties(self):
    #================================
        # Update feature properties
        for feature in self.__features:
            if not settings.get('authoring', False):
                if ('auto-hide' in feature.get_property('class', '')
                or feature.get_property('node', False)
                or feature.get_property('type') == 'nerve' and feature.get_property('kind') != 'centreline'):
                    # Nerve and ``auto-hide`` features are included only if used by connectivity
                    feature.set_property('exclude', True)
            if feature.get_property('type') == 'nerve' or feature.get_property('node', False):
                feature.set_property('tile-layer', PATHWAYS_TILE_LAYER)
            if self.__exported:
                # Save relationship between id/class and internal feature id
                self.__flatmap.save_feature_for_node_lookup(feature)

#===============================================================================

class MapLayer(FeatureLayer):
    def __init__(self, id: str, source: 'MapSource', exported=False, min_zoom: Optional[int]=None):
        super().__init__(id, source.flatmap, exported=exported)
        self.__source = source
        self.__boundary_feature = None
        self.__bounds = source.bounds
        self.__outer_geometry = shapely.box(*source.bounds)
        self.__detail_features: list[Feature] = []
#*        self.__ontology_data = self.options.ontology_data
        self.__raster_layers: list[RasterLayer] = []
        self.__min_zoom = min_zoom if min_zoom is not None else source.min_zoom
        self.__max_zoom = source.max_zoom

    @property
    def boundary_feature(self):
        return self.__boundary_feature

    @boundary_feature.setter
    def boundary_feature(self, value):
        self.__boundary_feature = value

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.__bounds

    @property
    def detail_features(self) -> list[Feature]:
        return self.__detail_features

    @property
    def detail_layer(self) -> bool:
        return (self.__source.base_feature is not None)

    @property
    def max_zoom(self) -> Optional[int]:
        return self.__max_zoom
    @max_zoom.setter
    def max_zoom(self, zoom):
        self.__max_zoom = zoom

    @property
    def min_zoom(self) -> int:
        return self.__min_zoom

    @property
    def outer_geometry(self) -> BaseGeometry:
        return self.__outer_geometry

    @property
    def raster_layers(self) -> list['RasterLayer']:
        return self.__raster_layers

    @property
    def source(self) -> 'MapSource':
        return self.__source

    def add_feature(self, feature: Feature):    # type: ignore
    #=======================================
        if self.__min_zoom is not None and not feature.has_property('minzoom'):
            feature.set_property('minzoom', max(self.__min_zoom-1, 0))
        super().add_feature(feature, map_layer=self)
        if feature.has_property('details'):
            self.__detail_features.append(feature)

    def add_raster_layer(self, layer_id: str, extent, map_source: 'MapSource', min_zoom: Optional[int]=None, local_world_to_base=None):
    #==================================================================================================================================
        if map_source.raster_source is not None:
            if min_zoom is not None:
                min_zoom += 1
            else:
                min_zoom = self.min_zoom
            if map_source.base_feature is not None:
                min_zoom -= 3
            self.__raster_layers.append(RasterLayer(layer_id.replace('/', '_'), extent, map_source, min_zoom,
                                                    local_world_to_base))

    def add_group_features(self, group_name: str, features: list[Feature], tile_layer=FEATURES_TILE_LAYER, outermost=False) -> Optional[Feature]:
    #===========================================================================================================================================
        base_properties = {
            'tile-layer': tile_layer
            }

        layer_features = []    # Features that will be added to the layer
        grouped_properties = {
            'group': True,
            'interior': True,
            'tile-layer': tile_layer
        }

        # We first find our boundary polygon(s)
        boundary_class = None
        boundary_lines = []
        boundary_polygon = None
        dividers = []
        regions = []

        debug_group = False
        child_class = None
        generate_group = False
        single_features = [ feature for feature in features if not feature.is_group ]
        for feature in single_features:
            if feature.get_property('boundary'):
                if feature.get_property('group'):
                    log.error(f'Group element cannot have `.boundary` markup')
                if outermost:
                    if self.__boundary_feature is not None:
                        raise ValueError('Layer cannot have multiple boundaries: {}'.format(feature))
                    self.__boundary_feature = feature
                    layer_features.append(feature)
                elif feature.geom_type == 'LineString':
                    boundary_lines.append(extend_line(feature.geometry))
                elif feature.geom_type == 'Polygon':
                    if boundary_polygon is not None:
                        raise GroupValueError('{} can only have one boundary shape:'.format(group_name), features)
                    boundary_polygon = feature.geometry
                    if feature.visible():
                        layer_features.append(feature)
                cls = feature.get_property('class')
                if cls is not None:
                    if cls != boundary_class:
                        boundary_class = cls
                    else:
                        raise ValueError('Class of boundary shapes have changed in {}: {}'.format(group_name, feature))
            elif feature.get_property('group'):
                generate_group = True
                child_class = feature.pop_property('children')
                grouped_properties.update(feature.properties)
            elif feature.get_property('region'):
                regions.append(self.flatmap.new_feature(self.id, feature.geometry.representative_point(), feature.properties))
            elif feature.get_property('divider'):
                if feature.geom_type == 'LineString':
                    dividers.append(feature.geometry)
                elif feature.geom_type == 'Polygon':
                    dividers.append(feature.geometry.boundary)
                if feature.visible():
                    layer_features.append(feature)
            elif not feature.get_property('interior'):
                layer_features.append(feature)

        interior_features = []
        for feature in features:
            if feature.get_property('interior') and not feature.get_property('boundary'):
                interior_features.append(feature)

        if boundary_polygon is not None and len(boundary_lines):
            raise GroupValueError("{} can't be bounded by both a closed shape and lines:".format(group_name), features)
        elif len(boundary_lines):
            if debug_group:
                save_geometry(shapely.MultiLineString(boundary_lines), 'boundary_lines.wkt')
            try:
                boundary_polygon = make_boundary(boundary_lines)
            except ValueError as err:
                raise GroupValueError('{}: {}'.format(group_name, str(err)), features) from None

        if boundary_polygon is not None:
            layer_features.append(
                self.flatmap.new_feature(
                    self.id,
                    boundary_polygon,
                    base_properties))

            if len(dividers):
                # For all line dividers, if the end of a line is 'close to' another line
                # then extend the line end in about the same direction until it touches
                # the other. NB. may need to 'bend towards' the other...
                #
                # And then only add these cleaned up lines as features, not the original dividers

                if debug_group:
                    save_geometry(shapely.MultiLineString(dividers), 'dividers.wkt')
                dividers.append(boundary_polygon.boundary)

                divider_lines = connect_dividers(dividers, debug_group)
                if debug_group:
                    save_geometry(shapely.MultiLineString(divider_lines), 'divider_lines.wkt')

                polygon_boundaries = shapely.ops.unary_union(divider_lines)
                if debug_group:
                    save_geometry(polygon_boundaries, 'polygon_boundaries.wkt')

                polygons = list(shapely.ops.polygonize(polygon_boundaries))

                for n, polygon in enumerate(polygons):
                    if debug_group:
                        save_geometry(polygon, f'polygon_{n}.wkt')
                    prepared_polygon = shapely.prepared.prep(polygon)
                    region_id = None
                    region_properties = base_properties.copy()
                    for region in filter(lambda p: prepared_polygon.contains(p.geometry), regions):
                        region_properties.update(region.properties)
                        layer_features.append(self.flatmap.new_feature(self.id, polygon, region_properties))
                        break
        else:
            for feature in features:
                if feature.get_property('region'):
                    raise ValueError('Region dividers in group {} must have a boundary: {}'.format(group_name, feature))

        if not outermost and interior_features:
            interior_polygons = []
            for feature in interior_features:
                if feature.geom_type == 'Polygon':
                    interior_polygons.append(feature.geometry)
                elif feature.geom_type == 'MultiPolygon':
                    interior_polygons.extend(list(feature.geometry.geoms))
            interior_polygon = shapely.ops.unary_union(interior_polygons)
            for feature in layer_features:
                if (feature.has_property('markup')
                and feature.get_property('exterior')
                and feature.geom_type in ['Polygon', 'MultiPolygon']):
                    feature.geometry = feature.geometry.buffer(0).difference(interior_polygon)

        # Construct a MultiPolygon containing all of the group's polygons
        # But only if the group contains a `.group` element...

        feature_group = None  # Our returned Feature
        if generate_group:
            grouped_polygon_features = [ feature for feature in features if feature.is_group ]
            for feature in layer_features:
                grouped_polygon_features.append(feature)

            grouped_polygons = []
            for feature in grouped_polygon_features:
                if feature.geom_type == 'Polygon':
                    grouped_polygons.append(feature.geometry)
                elif feature.geom_type == 'MultiPolygon':
                    grouped_polygons.extend(list(feature.geometry.geoms))       # type: ignore
            if len(grouped_polygons):
                feature_group = self.flatmap.new_feature(
                        self.id,
                        shapely.MultiPolygon(grouped_polygons).buffer(0),
                        grouped_properties, is_group=True)
                layer_features.append(feature_group)
                # So that any grouped lines don't have a duplicate id
                grouped_properties.pop('id', None)

            grouped_lines = []
            for feature in grouped_polygon_features:
                if feature.get_property('tile-layer') != PATHWAYS_TILE_LAYER:
                    if feature.geom_type == 'LineString':
                        grouped_lines.append(feature.geometry)
                    elif feature.geom_type == 'MultiLineString':
                        grouped_lines.extend(list(feature.geometry.geoms))      # type: ignore
            if len(grouped_lines):  ## should polygons take precedence over lines???
                                    ## at least for assigning ID...
                feature_group = self.flatmap.new_feature(
                      self.id,
                      shapely.MultiLineString(grouped_lines),
                      grouped_properties, is_group=True)
                layer_features.append(feature_group)

        # Feature specific properties have precedence over group's
        default_properties = base_properties.copy()
        if child_class is not None:
            # Default class for all of the group's child shapes
            default_properties['class'] = child_class

        # Actually add the features to the layer
        for feature in layer_features:
            if feature.geometry is not None:
                for (key, value) in default_properties.items():
                    if not feature.has_property(key):
                        feature.set_property(key, value)
                self.add_feature(feature)

        return feature_group

#===============================================================================

class RasterLayer(object):
    """
    Details of layer for creating raster tiles.

    :param id: the ``id`` of the source layer to rasterise
    :type id: str
    :param extent: the extent of the base map in which the layer is to be rasterised
                   as decimal latitude and longitude coordinates.
    :type extent: tuple(south, west, north, east)
    :param map_source: the source of the layer's data
    :type map_source: :class:`~mapmaker.sources.MapSource`
    :param min_zoom: The minimum zoom level to generate tiles for.
                     Optional, defaults to ``min_zoom`` of ``map_source``.
    :type map_zoom: int
    :param local_world_to_base: an optional transform from the raster layer's
                                local world coordinates to the base map's
                                world coordinates. Defaults to ``None``, meaning
                                the :class:`~mapmaker.geometry.Transform.Identity()` transform
    :type local_world_to_base: :class:`~mapmaker.geometry.Transform`
    """
    def __init__(self, id: str, extent, map_source: 'MapSource',
                 min_zoom:Optional[int]=None, max_zoom: Optional[int]=None, local_world_to_base=None):
        self.__id = '{}_image'.format(id)
        self.__extent = extent
        self.__map_source = map_source
        self.__flatmap = map_source.flatmap
        self.__max_zoom = max_zoom if max_zoom is not None else settings.get('maxRasterZoom', map_source.max_zoom)
        self.__min_zoom = min_zoom if min_zoom is not None else map_source.min_zoom
        self.__local_world_to_base = local_world_to_base

    @property
    def extent(self):
        return self.__extent

    @property
    def flatmap(self):
        return self.__flatmap

    @property
    def id(self):
        return self.__id

    @property
    def local_world_to_base(self):
        return self.__local_world_to_base

    @property
    def map_source(self):
        return self.__map_source

    @property
    def max_zoom(self):
        return self.__max_zoom

    @property
    def min_zoom(self):
        return self.__min_zoom

    @property
    def source_data(self) -> bytes:
        return self.__map_source.raster_source.data

    @property
    def source_extent(self):
        return self.__map_source.extent

    @property
    def source_kind(self):
        return self.__map_source.raster_source.kind

    @property
    def source_path(self):
        return self.__map_source.raster_source.source_path

    @property
    def source_range(self):
        return self.__map_source.source_range

#===============================================================================
