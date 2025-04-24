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

from mapmaker import ZOOM_OFFSET_FROM_BASE
from mapmaker.exceptions import GroupValueError
from mapmaker.geometry import bounds_to_extent, connect_dividers, extend_line, make_boundary
from mapmaker.geometry import bounds_centroid, MapBounds, MapExtent, merge_bounds, translate_extent
from mapmaker.geometry import save_geometry, Transform
from mapmaker.settings import MAP_KIND, settings
from mapmaker.utils import FilePath, log

if TYPE_CHECKING:
    from mapmaker.sources import MapSource, RasterSource
    from . import FlatMap, SourceBackground

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
    def offset(self) -> tuple[float, float]:
        return (0.0, 0.0)

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
        self.__offset = (0.0, 0.0)
        self.__zoom_point_id = None

    @property
    def boundary_feature(self) -> Optional[Feature]:
        return self.__boundary_feature
    @boundary_feature.setter
    def boundary_feature(self, value: Feature):
        self.__boundary_feature = value

    @property
    def bounds(self) -> MapBounds:
        return self.__bounds

    @property
    def detail_features(self) -> list[Feature]:
        return self.__detail_features

    @property
    def detail_layer(self) -> bool:
        return (self.__source.base_feature is not None)

    @property
    def extent(self) -> MapExtent:
        return bounds_to_extent(self.__bounds)

    @property
    def max_zoom(self) -> int:
        return self.__max_zoom
    @max_zoom.setter
    def max_zoom(self, zoom: int):
        self.__max_zoom = zoom

    @property
    def min_zoom(self) -> int:
        return self.__min_zoom

    @property
    def outer_geometry(self) -> BaseGeometry:
        return self.__outer_geometry

    @property
    def parent_layer(self) -> Optional[str]:
        if (base_feature := self.__source.base_feature) is not None:
            return base_feature.get_property('layer')
        return None

    @property
    def raster_layers(self) -> list['RasterLayer']:
        return self.__raster_layers

    @property
    def source(self) -> 'MapSource':
        return self.__source

    @property
    def zoom_point_id(self) -> Optional[int]:
        return self.source.zoom_point_id

    def add_feature(self, feature: Feature):    # type: ignore
    #=======================================
        if self.__min_zoom is not None and not feature.has_property('minzoom'):
            feature.set_property('minzoom', max(self.__min_zoom-1, 0))
        super().add_feature(feature, map_layer=self)
        if feature.has_property('details'):
            self.__detail_features.append(feature)
        if self.flatmap.map_kind == MAP_KIND.FUNCTIONAL:
            if (hyperlinks := feature.get_property('hyperlinks')) is not None:
                if 'flatmap' in hyperlinks and (zoom_point := self.flatmap.add_zoom_point(feature)) is not None:
                    zoom_point.set_property('hyperlinks', hyperlinks)

    def __find_feature(self, feature_id: str) -> Optional[Feature]:
    #==============================================================
        return self.flatmap.get_feature(feature_id.replace(" ", "_"))

    def align_layer(self, feature_alignment: list[tuple[str, str]]):
    #===============================================================
        base_feature_bounds = None
        layer_feature_bounds = None
        for (base_feature_id, layer_feature_id) in feature_alignment:
            if (base_feature := self.__find_feature(base_feature_id)) is None:
                log.warning('Cannot find base feature for layer alignment', layer=self.id, feature=base_feature_id)
            elif base_feature_bounds is None:
                base_feature_bounds = base_feature.bounds
            else:
                base_feature_bounds = merge_bounds(base_feature_bounds, base_feature.bounds)
            if (layer_feature := self.__find_feature(layer_feature_id)) is None:
                log.warning("Cannot find layer's feature for alignment", layer=self.id, feature=layer_feature_id)
            elif layer_feature_bounds is None:
                layer_feature_bounds = layer_feature.bounds
            else:
                layer_feature_bounds = merge_bounds(layer_feature_bounds, layer_feature.bounds)
        if base_feature_bounds is not None and layer_feature_bounds is not None:
            base_centroid = bounds_centroid(base_feature_bounds)
            layer_centroid = bounds_centroid(layer_feature_bounds)
            self.__offset = ((base_centroid[0] - layer_centroid[0]),
                             (base_centroid[1] - layer_centroid[1]))
            if self.__offset != (0.0, 0.0):
                for feature in self.features:
                    feature.geometry = shapely.affinity.translate(feature.geometry, xoff=self.__offset[0], yoff=self.__offset[1])
            self.__bounds = (self.__bounds[0] + self.__offset[0], self.__bounds[1] + self.__offset[1],
                             self.__bounds[2] + self.__offset[0], self.__bounds[3] + self.__offset[1])

    def create_feature_groups(self):
    #===============================
        for (group_id, feature_ids) in self.flatmap.properties_store.feature_groups(self.id).items():
            if len(feature_ids):
                group_bounds = None
                for feature_id in feature_ids:
                    if (feature := self.__find_feature(feature_id)) is None:
                        log.warning('Cannot find source feature for feature group', layer=self.id, group=group_id, feature=feature_id)
                    elif group_bounds is None:
                        group_bounds = feature.bounds
                    else:
                        group_bounds = merge_bounds(group_bounds, feature.bounds)
                if group_bounds is not None:
                    self.flatmap.new_feature(self.id, shapely.box(*group_bounds), {
                        'id': group_id,
                        'exclude': True
                    })

    def add_raster_layers(self, extent: MapBounds, map_source: 'MapSource', layer_id: Optional[str]=None,
                          min_zoom: Optional[int]=None, local_world_to_base: Optional[Transform]=None):
    #==================================================================================================
        if min_zoom is not None:
            min_zoom += 1
        else:
            min_zoom = self.min_zoom
        if map_source.base_feature is not None:
            min_zoom -= ZOOM_OFFSET_FROM_BASE
        if self.__offset != (0.0, 0.0):
            extent = translate_extent(extent, self.__offset)
        self.__raster_layers = [RasterLayer(raster_source, extent,
                                            min_zoom=min_zoom, local_world_to_base=local_world_to_base)
                                    for raster_source in map_source.raster_sources]

    def add_group_features(self, group_name: str, features: list[Feature],
                           tile_layer=FEATURES_TILE_LAYER, outermost=False) -> Optional[Feature]:
    #============================================================================================
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

    :param raster_source: the source to be rasterised
    :param extent: the extent of the base map in which the layer is to be rasterised
                   as decimal latitude and longitude coordinates.
    :param min_zoom: The minimum zoom level to generate tiles for.
                     Optional, defaults to ``min_zoom`` of ``map_source``.
    :param local_world_to_base: an optional transform from the raster layer's
                                local world coordinates to the base map's
                                world coordinates. Defaults to ``None``, meaning
                                the :class:`~mapmaker.geometry.Transform.Identity()` transform
    """
    def __init__(self, raster_source: 'RasterSource', extent: MapBounds,
                 min_zoom:Optional[int]=None, max_zoom: Optional[int]=None,
                 local_world_to_base: Optional[Transform]=None):
        self.__id = raster_source.id
        self.__extent = extent
        self.__raster_source = raster_source
        self.__map_source = raster_source.map_source
        self.__flatmap = self.__map_source.flatmap
        self.__max_zoom = max_zoom if max_zoom is not None else self.__map_source.max_zoom
        self.__min_zoom = min_zoom if min_zoom is not None else self.__map_source.min_zoom
        self.__local_world_to_base = local_world_to_base
        self.__background_layer = raster_source.background_layer

    @property
    def background_layer(self) -> bool:
        return self.__background_layer

    @property
    def extent(self) -> MapBounds:
        return self.__extent

    @property
    def flatmap(self) -> 'FlatMap':
        return self.__flatmap

    @property
    def id(self) -> str:
        return self.__id

    @property
    def local_world_to_base(self) -> Optional[Transform]:
        return self.__local_world_to_base

    @property
    def map_source(self) -> 'MapSource':
        return self.__map_source

    @property
    def max_zoom(self) -> int:
        return self.__max_zoom

    @property
    def min_zoom(self) -> int:
        return self.__min_zoom

    @property
    def source_data(self) -> bytes:
        return self.__raster_source.data

    @property
    def source_extent(self) -> MapBounds:
        return self.__map_source.extent

    @property
    def source_kind(self) -> str:
        return self.__raster_source.kind

    @property
    def source_path(self) -> Optional[FilePath]:
        return self.__raster_source.source_path

    @property
    def source_range(self) -> Optional[list[int]]:
        return self.__map_source.source_range

    @property
    def transform(self) -> Optional[Transform]:
        return self.__raster_source.transform

#===============================================================================
