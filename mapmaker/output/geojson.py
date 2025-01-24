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

#===============================================================================

import shapely.affinity
import shapely.geometry

#===============================================================================

from mapmaker.flatmap import FlatMap, MapLayer
from mapmaker.geometry import mercator_transform
from mapmaker.settings import MAP_KIND, settings
from mapmaker.utils import log, ProgressBar, set_as_list

from . import ENCODED_FEATURE_PROPERTIES, EXPORTED_FEATURE_PROPERTIES

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

        layer_offset = self.__layer.offset
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
                name: value for name in EXPORTED_FEATURE_PROPERTIES
                    if (value := feature.get_property(name)) is not None
                    and value != ''
            }
            properties.update({
                name: json.dumps(value) for (name, value) in properties.items()
                    if name in ENCODED_FEATURE_PROPERTIES
            })
            geometry = feature.geometry
            if layer_offset != (0.0, 0.0):
                geometry = shapely.affinity.translate(geometry, xoff=layer_offset[0], yoff=layer_offset[1])
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
                geojson['properties']['scale'] = 10
            geojson['properties'].update(properties)

            properties['bounds'] = geojson['properties']['bounds']
            if 'Polygon' in geometry.geom_type:
                properties['markerPosition'] = list(list(mercator_geometry.representative_point().coords)[0])
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
