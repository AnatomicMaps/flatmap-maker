#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019  David Brooks
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

from collections import defaultdict
import json
import math
import os
from typing import cast

#===============================================================================

import shapely.affinity
import shapely.geometry
import shapely.ops

#===============================================================================

from mapmaker.flatmap import FlatMap, MapLayer
from mapmaker.geometry import mercator_transform
from mapmaker.settings import MAP_KIND, settings
from mapmaker.utils import log, ProgressBar, set_as_list

from . import ENCODED_FEATURE_PROPERTIES, EXPORTED_FEATURE_PROPERTIES

#===============================================================================

# Earth circumference (WGS84 equatorial radius for Web Mercator EPSG:3857)
EARTH_CIRCUMFERENCE = 2 * math.pi * 6378137.0  # meters

#===============================================================================

class GeoJSONOutput(object):
    def __init__(self, flatmap: FlatMap, layer: MapLayer, output_dir: str):
    #======================================================================
        self.__flatmap = flatmap
        self.__layer = layer
        self.__map_area = flatmap.area
        self.__output_dir = output_dir
        self.__geojson_layers = defaultdict(list)

    def save(self, features, pretty_print=False):
    #============================================
        self.__save_features(features)
        saved_filenames = {}
        for (geojson_id, features) in self.__geojson_layers.items():
            filename = os.path.join(self.__output_dir, f'{geojson_id}.json')
            saved_filenames[geojson_id] = filename
            with open(filename, 'w') as output_file:
                if pretty_print:
                    feature_collection = {
                        'type': 'FeatureCollection',
                        'features': features
                    }
                    output_file.write(json.dumps(feature_collection, indent=4, default=set_as_list))
                else:
                    # Tippecanoe doesn't need a FeatureCollection
                    # Delimit features with RS...LF   (RS = 0x1E)
                    for feature in features:
                        output_file.write('\x1E{}\x0A'.format(json.dumps(feature, default=set_as_list)))
        return saved_filenames

    def __save_features(self, features):
    #===================================
        progress_bar = ProgressBar(total=len(features),
            unit='ftr', ncols=40,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')

        exported_properties = set(EXPORTED_FEATURE_PROPERTIES + self.__flatmap.manifest.exported_properties)
        for feature in features:
            if not settings.get('authoring', False):
                feature.properties.pop('warning', None)
                if 'error' in feature.properties:
                    log.warning(f'Feature not output because it has errors: {feature.id}')
                    progress_bar.update(1)
                    continue
            if feature.get_property('exclude', False):
                progress_bar.update(1)
                continue
            properties = {
                name: value for name in exported_properties
                    if (value := feature.get_property(name)) is not None
                    and value != ''
            }
            geometry = feature.geometry
            area = geometry.area
            mercator_geometry = mercator_transform(geometry)
            tile_layer = properties['tile-layer']
            tippe_layer = f'{self.__layer.id}_{tile_layer}'.replace('/', '_')
            geojson = {
                'type': 'Feature',
                'id': feature.geojson_id,
                'tippecanoe' : {
                    'layer' : tippe_layer
                },
                'geometry': shapely.geometry.mapping(mercator_geometry),
                'properties': {
                    'bounds': list(mercator_geometry.bounds),
                    'area': area,
                    'length': geometry.length,
                    'layer': self.__layer.id,
                }
            }
            if 'maxzoom' in properties:
                geojson['tippecanoe']['maxzoom'] = properties['maxzoom']
            if 'minzoom' in properties:
                geojson['tippecanoe']['minzoom'] = properties['minzoom']
            if area > 0:
                scale = math.log(math.sqrt(self.__map_area/area), 2)
                geojson['properties']['scale'] = scale
                if scale > 6 and 'group' not in properties and 'minzoom' not in properties:
                    geojson['tippecanoe']['minzoom'] = 4
            else:
                if (nodes:=self.__flatmap.connectivity()['paths'].get(feature.models)):
                    zoom_range = self.__get_path_zoom_range(nodes)
                    geojson['properties']['minzoom'] = zoom_range[0]
                    geojson['properties']['maxzoom'] = zoom_range[1]
                geojson['properties']['scale'] = 10
            geojson['properties'].update(properties)

            properties['bounds'] = geojson['properties']['bounds']
            if 'Polygon' in geometry.geom_type:
                representative_point = shapely.ops.polylabel(cast(shapely.geometry.Polygon, mercator_geometry), tolerance=0.1)
                properties['markerPosition'] = list(list(representative_point.coords)[0])
            else:
                properties['markerPosition'] = list(list(mercator_geometry.centroid.coords)[0])
            properties['geometry'] = geojson['geometry']['type']
            properties['layer'] = self.__layer.id
            if mercator_geometry.geom_type == 'LineString':
                boundary = mercator_geometry.boundary
                if (len(geoms := boundary.geoms)) == 2:
                    properties['pathStartPosition'] = shapely.geometry.mapping(geoms[0])['coordinates']
                    properties['pathEndPosition'] = shapely.geometry.mapping(geoms[1])['coordinates']
                if self.__flatmap.map_kind == MAP_KIND.CENTRELINE and feature.properties.get('kind') == 'centreline':
                    properties['coordinates'] = geojson['geometry']['coordinates']

            # We don't want encoded JSON in ``geojson['properties']`` so ``properties`` encoding has to be
            # after GeoJSON has been updated
            properties.update({
                name: json.dumps(value) for (name, value) in properties.items()
                    if name in ENCODED_FEATURE_PROPERTIES
            })

            # Output the anatomical nodes associated with the feature
            if len(feature.anatomical_nodes):
                properties['anatomical-nodes'] = feature.anatomical_nodes

            # The layer's annotation has property details for each feature.
            # NB. These, and only these, properties are passed to the viewer
            #     as the feature's ``annotations`` (indexed by geojson_id)
            self.__layer.annotate(feature, properties)

            self.__geojson_layers[tippe_layer].append(geojson)
            progress_bar.update(1)

        progress_bar.close()

    def __get_path_zoom_range(self, nodes):
        path_min_coverage = settings.get('pathMinCoverage', 0.7)
        path_max_coverage = settings.get('pathMaxCoverage', 5.0)

        points = [geom.centroid
                    for node in nodes.get('nodes', [])
                        if (f := self.__flatmap.get_feature_by_geojson_id(node)) is not None
                            and (geom := f.geometry) is not None]

        if len(points) > 1:
            # extent
            xs = [p.x for p in points]
            ys = [p.y for p in points]
            # World-space extents (meters, EPSG:3857)
            x_extent = max(xs) - min(xs)
            y_extent = max(ys) - min(ys)
            max_dist = 0.0
            for i, p1 in enumerate(points):
                for p2 in points[i+1:]:
                    dist = math.hypot(p2.x - p1.x, p2.y - p1.y)
                    if dist > max_dist:
                        max_dist = dist
            extent = max(x_extent, y_extent, max_dist)
            if not math.isfinite(extent) or extent <= 0:
                return self.__flatmap.min_zoom, self.__flatmap.max_zoom

            # minzoom and maxzoom
            z_min = math.ceil(math.log2((path_min_coverage * EARTH_CIRCUMFERENCE) / extent))
            z_max = math.floor(math.log2((path_max_coverage * EARTH_CIRCUMFERENCE) / extent))
            if z_max < z_min:
                z_max = z_min
            z_min = max(self.__flatmap.min_zoom, z_min)
            z_max = min(self.__flatmap.max_zoom, z_max)
            if z_min >= self.__flatmap.max_zoom:
                z_min = self.__flatmap.max_zoom - 1
                z_max = self.__flatmap.max_zoom
            return z_min, z_max

        return self.__flatmap.min_zoom, self.__flatmap.max_zoom
