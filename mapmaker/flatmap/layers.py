#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019, 2020  David Brooks
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

import shapely.geometry

#===============================================================================

from mapmaker import MIN_ZOOM
from mapmaker.exceptions import GroupValueError
from mapmaker.geometry import connect_dividers, extend_line, make_boundary
from mapmaker.geometry import save_geometry

#===============================================================================

class FeatureLayer(object):
    def __init__(self, id, base_layer=False):
        self.__id = id
        self.__annotations = {}
        self.__base_layer = base_layer
        self.__description = 'Layer {}'.format(id)
        self.__features = []
        self.__features_by_id = {}
        self.__feature_types = []  ## No longer used ???

    @property
    def annotations(self):
        return self.__annotations

    @property
    def base_layer(self):
        return self.__base_layer

    @property
    def description(self):
        return self.__description

    @description.setter
    def description(self, value):
        self.__description = value

    @property
    def features(self):
        return self.__features

    @property
    def features_by_id(self):
        return self.__features_by_id

    @property
    def feature_types(self):
        return self.__feature_types

    @property
    def id(self):
        return self.__id

    @property
    def raster_layers(self):
        return []

    def add_feature(self, feature):
    #==============================
        self.__features.append(feature)
        if feature.id is not None:
            self.__features_by_id[feature.id] = feature
        self.__feature_types.append({
            'type': feature.get_property('geometry')  ## Unused ???
        })

    def annotate(self, feature, properties):
    #=======================================
        self.__annotations[feature.feature_id] = properties

    def set_feature_properties(self, map_properties):
    #===============================================
        # Update feature properties from JSON properties file
        for feature in self.__features:
            map_properties.update_feature_properties(feature.properties)

#===============================================================================

class MapLayer(FeatureLayer):
    def __init__(self, id, source, base_layer=False):
        super().__init__(id, base_layer)
        self.__source = source
        self.__flatmap = source.flatmap
        self.__boundary_id = None
        self.__detail_features = []
#*        self.__ontology_data = self.options.ontology_data
        self.__queryable_nodes = False
        self.__raster_layers = []
        self.__zoom = None

    @property
    def boundary_id(self):
        return self.__boundary_id

    @boundary_id.setter
    def boundary_id(self, value):
        self.__boundary_id = value

    @property
    def detail_features(self):
        return self.__detail_features

    @property
    def details_layer(self):
        return self.__details_layer

    @property
    def flatmap(self):
        return self.__flatmap

    @property
    def queryable_nodes(self):
        return self.__queryable_nodes

    @queryable_nodes.setter
    def queryable_nodes(self, value):
        self.__queryable_nodes = value

    @property
    def raster_layers(self):
        return self.__raster_layers

    @property
    def source(self):
        return self.__source

    @property
    def zoom(self):
        return self.__zoom

    @zoom.setter
    def zoom(self, value):
        self.__zoom = value

    def add_feature(self, feature):
    #==============================
        super().add_feature(feature)
        if feature.has_property('details'):
            self.__detail_features.append(feature)

    def add_raster_layer(self, id, extent, map_source, min_zoom=MIN_ZOOM, local_world_to_base=None):
    #===============================================================================================
        if map_source.raster_source is not None:
            self.__raster_layers.append(RasterLayer(id, extent, map_source, min_zoom, local_world_to_base))

    def add_nerve_details(self):
    #===========================
        # Add polygon features for nerve cuffs
        nerve_polygons = []
        for feature in self.features:
            if feature.get_property('type') == 'nerve':
                if not feature.has_property('nerveId'):
                    feature.set_property('nerveId', feature.feature_id)  # Used in map viewer
                if feature.geom_type == 'LineString':
                    nerve_polygon_feature = self.__source.flatmap.new_feature(
                        shapely.geometry.Polygon(feature.geometry.coords), feature.properties)
                    nerve_polygon_feature.set_property('nerveId', feature.feature_id)  # Used in map viewer
                    nerve_polygon_feature.set_property('tile-layer', 'pathways')
                    nerve_polygons.append(nerve_polygon_feature)
        self.features.extend(nerve_polygons)

    def add_features(self, group_name, features, outermost=False):
    #=============================================================
        base_properties = {
            'tile-layer': 'features'
            }

        group_features = []
        grouped_properties = {
            'group': True,
            'interior': True,
            'tile-layer': 'features'
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
        single_features = [ feature for feature in features if not feature.has_children ]
        for feature in single_features:
            if feature.get_property('boundary'):
                if outermost:
                    if self.__boundary_id is not None:
                        raise ValueError('Layer cannot have multiple boundaries: {}'.format(feature))
                    self.__boundary_id = feature.feature_id
                    group_features.append(feature)
                elif feature.geom_type == 'LineString':
                    boundary_lines.append(extend_line(feature.geometry))
                elif feature.geom_type == 'Polygon':
                    if boundary_polygon is not None:
                        raise GroupValueError('{} can only have one boundary shape:'.format(group_name), features)
                    boundary_polygon = feature.geometry
                    if not feature.get_property('invisible'):
                        group_features.append(feature)
                cls = feature.get_property('class')
                if cls is not None:
                    if cls != boundary_class:
                        boundary_class = cls
                    else:
                        raise ValueError('Class of boundary shapes have changed in {}: {}'.format(group_name, feature))
            elif feature.get_property('group'):
                generate_group = True
                child_class = feature.del_property('children')
                grouped_properties.update(feature.properties)
            elif feature.get_property('region'):
                regions.append(self.__flatmap.new_feature(feature.geometry.representative_point(), feature.properties))
            elif not feature.has_property('markup') or feature.get_property('divider'):
                if feature.geom_type == 'LineString':
                    dividers.append(feature.geometry)
                elif feature.geom_type == 'Polygon':
                    dividers.append(feature.geometry.boundary)
                if not feature.get_property('invisible'):
                    group_features.append(feature)
            elif feature.has_property('class') or not feature.get_property('interior'):
                group_features.append(feature)

        interior_features = []
        for feature in features:
            if feature.get_property('interior') and not feature.get_property('boundary'):
                interior_features.append(feature)

        if boundary_polygon is not None and len(boundary_lines):
            raise GroupValueError("{} can't be bounded by both a closed shape and lines:".format(group_name), features)

        elif boundary_polygon is not None or len(boundary_lines):
            if len(boundary_lines):
                if debug_group:
                    save_geometry(shapely.geometry.MultiLineString(boundary_lines), 'boundary_lines.wkt')
                try:
                    boundary_polygon = make_boundary(boundary_lines)
                except ValueError as err:
                    raise GroupValueError('{}: {}'.format(group_name, str(err)), features)

            group_features.append(
                self.__flatmap.new_feature(
                    boundary_polygon,
                    base_properties))

            if len(dividers):
                # For all line dividers, if the end of a line is 'close to' another line
                # then extend the line end in about the same direction until it touches
                # the other. NB. may need to 'bend towards' the other...
                #
                # And then only add these cleaned up lines as features, not the original dividers

                dividers.append(boundary_polygon.boundary)
                if debug_group:
                    save_geometry(shapely.geometry.MultiLineString(dividers), 'dividers.wkt')

                divider_lines = connect_dividers(dividers, debug_group)
                if debug_group:
                    save_geometry(shapely.geometry.MultiLineString(divider_lines), 'divider_lines.wkt')

                polygon_boundaries = shapely.ops.unary_union(divider_lines)
                if debug_group:
                    save_geometry(polygon_boundaries, 'polygon_boundaries.wkt')

                polygons = list(shapely.ops.polygonize(polygon_boundaries))

                for n, polygon in enumerate(polygons):
                    prepared_polygon = shapely.prepared.prep(polygon)
                    region_id = None
                    region_properties = base_properties.copy()
                    for region in filter(lambda p: prepared_polygon.contains(p.geometry), regions):
                        region_properties.update(region.properties)
                        group_features.append(self.__flatmap.new_feature(polygon, region_properties))
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
                    interior_polygons.extend(list(feature.geometry))
            interior_polygon = shapely.ops.unary_union(interior_polygons)
            for feature in group_features:
                if (feature.has_property('markup')
                and feature.get_property('exterior')
                and feature.geom_type in ['Polygon', 'MultiPolygon']):
                    feature.geometry = feature.geometry.buffer(0).difference(interior_polygon)

        # Construct a MultiPolygon containing all of the group's polygons
        # But only if the group contains a `.group` element...

        feature_group = None  # Our returned Feature
        if generate_group:
            grouped_polygon_features = [ feature for feature in features if feature.has_children ]
            for feature in group_features:
                grouped_polygon_features.append(feature)

            grouped_lines = []
            for feature in grouped_polygon_features:
                if feature.get_property('tile-layer') != 'pathways':
                    if feature.geom_type == 'LineString':
                        grouped_lines.append(feature.geometry)
                    elif feature.geom_type == 'MultiLineString':
                        grouped_lines.extend(list(feature.geometry))
            if len(grouped_lines):
                feature_group = self.__flatmap.new_feature(
                      shapely.geometry.MultiLineString(grouped_lines),
                      grouped_properties, True)
                group_features.append(feature_group)
            grouped_polygons = []
            for feature in grouped_polygon_features:
                if feature.geom_type == 'Polygon':
                    grouped_polygons.append(feature.geometry)
                elif feature.geom_type == 'MultiPolygon':
                    grouped_polygons.extend(list(feature.geometry))
            if len(grouped_polygons):
                feature_group = self.__flatmap.new_feature(
                        shapely.geometry.MultiPolygon(grouped_polygons),
                        grouped_properties, True)
                group_features.append(feature_group)

        # Feature specific properties have precedence over group's

        default_properties = base_properties.copy()
        if child_class is not None:
            # Default class for all of the group's child shapes
            default_properties['class'] = child_class

        for feature in group_features:
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
    :param extent: the extent of the base map in which the layer is to be reasterised
                   as decimal latitude and longitude coordinates.
    :type extent: tuple(south, west, north, east)
    :param map_source: the source of the layer's data
    :type map_source: :class:`~mapmaker.sources.MapSource`
    :param min_zoom: The minimum zoom level to generate tiles for.
                     Optional, defaults to ``MIN_ZOOM``
    :type map_zoom: int
    :param local_world_to_base: an optional transform from the raster layer's
                                local world coordinates to the base map's
                                world coordinates. Defaults to ``None``, meaning
                                the :class:`~mapmaker.geometry.Identity` transform
    :type local_world_to_base: :class:`~mapmaker.geometry.Transform`
    """
    def __init__(self, id, extent, map_source, min_zoom=MIN_ZOOM, local_world_to_base=None):
        self.__id = '{}_image'.format(id)
        self.__extent = extent
        self.__map_source = map_source
        self.__min_zoom = min_zoom
        self.__local_world_to_base = local_world_to_base

    @property
    def extent(self):
        return self.__extent

    @property
    def id(self):
        return self.__id

    @property
    def map_source(self):
        return self.__map_source

    @property
    def min_zoom(self):
        return self.__min_zoom

    @property
    def source_data(self):
        return self.__map_source.raster_source.source_data

    @property
    def source_extent(self):
        return self.__map_source.extent

    @property
    def source_kind(self):
        return self.__map_source.raster_source.source_kind

    @property
    def local_world_to_base(self):
        return self.__local_world_to_base

#===============================================================================
