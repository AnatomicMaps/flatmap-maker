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

from collections import defaultdict, OrderedDict
import datetime
import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys
from urllib.parse import urljoin

#===============================================================================

import cv2
import numpy as np

#===============================================================================

from mapmaker import FLATMAP_VERSION, __version__
from mapmaker.geometry import Transform
from mapmaker.utils import log

#===============================================================================

from .flatmap.feature import Feature
from .flatmap.layers import FeatureLayer

from .geometry import bounds_to_extent, extent_to_bounds

from .knowledgebase import LabelDatabase

from .output.geojson import GeoJSONOutput
from .output.mbtiles import MBTiles
from .output.styling import MapStyle
from .output.tilejson import tile_json
from .output.tilemaker import RasterTileMaker

from .properties import JsonProperties

from .settings import settings

from .sources import MBFSource, PowerpointSource, SVGSource
from .sources.pmr import get_workspace

from .utils import make_url, path_json

#===============================================================================

class Manifest(object):
    def __init__(self, manifest_dir):
        manifest_path = os.path.join(manifest_dir, 'manifest.json')
        self.__manifest = path_json(manifest_path)
        manifest_url = make_url(manifest_path)
        if 'anatomicalMap' in self.__manifest:
            self.__manifest['anatomicalMap'] = urljoin(manifest_url, self.__manifest['anatomicalMap'])
        if 'properties' in self.__manifest:
            self.__manifest['properties'] = urljoin(manifest_url, self.__manifest['properties'])
        for source in self.__manifest['sources']:
            source['href'] = urljoin(manifest_url, source['href'])

    @property
    def anatomical_map(self):
        return self.__manifest.get('anatomicalMap')

    @property
    def id(self):
        return self.__manifest.get('id')

    @property
    def models(self):
        return self.__manifest.get('models')

    @property
    def properties(self):
        return self.__manifest.get('properties')

    @property
    def sources(self):
        return self.__manifest['sources']

#===============================================================================

class Flatmap(object):
    def __init__(self, options):
        # ``silent`` implies ``quiet``
        if options.get('silent', False):
            options['quiet'] = True

        # Setup logging
        log_file = options.get('logFile')
        if not options.get('silent', False):
            if options.get('quiet', False):
                logging.basicConfig(format='%(asctime)s %(message)s')
            else:
                logging.basicConfig(format='%(message)s')
            logging.getLogger().setLevel(logging.INFO)
            if log_file is not None:
                logger = logging.FileHandler(log_file)
                formatter = logging.Formatter('%(asctime)s %(message)s')
                logger.setFormatter(formatter)
                logging.getLogger().addHandler(logger)
        elif log_file is not None:
            logging.basicConfig(
                format='%(asctime)s %(message)s',
                filename=log_file,
                level=logging.INFO
            )

        # Check we have been given a map source
        if 'exposure' in options:
            self.__uri = options['exposure']
            Manifest(get_workspace(self.__uri))
        elif 'source' in options:
            self.__uri = None
            self.__manifest = Manifest(options['source'])
        else:
            raise ValueError('No map source nor exposure given')

        # Default base output directory to ``./flatmaps``.
        if 'output' not in options:
            options['output'] = './flatmaps'

        # Check zoom settings are valid
        min_zoom = options.get('minZoom', 2)
        max_zoom = options.get('maxZoom', 10)
        initial_zoom = options.get('initialZoom', 4)
        if min_zoom < 0 or min_zoom > max_zoom:
            raise ValueError('Min zoom must be between 0 and {}'.format(max_zoom))
        if max_zoom < min_zoom or max_zoom > 15:
            raise ValueError('Max zoom must be between {} and 15'.format(min_zoom))
        if initial_zoom < min_zoom or initial_zoom > max_zoom:
            raise ValueError('Initial zoom must be between {} and {}'.format(min_zoom, max_zoom))
        self.__zoom = (min_zoom, max_zoom, initial_zoom)

        # Save options into global ``settings`` dict
        settings.update(options)

        log('Mapmaker {}'.format(__version__))

        try:
            self.__id = self.__manifest.id
        except KeyError:
            raise ValueError('Map manifest requires an `id` field')

        self.__models = self.__manifest.models

        # Make sure our output directories exist
        map_base = options.get('output')
        if not os.path.exists(map_base):
            os.makedirs(map_base)
        self.__map_dir = os.path.join(map_base, self.__id)
        if options.get('clean', False):
            shutil.rmtree(self.__map_dir, True)
        if not os.path.exists(self.__map_dir):
            os.makedirs(self.__map_dir)

        # The vector tiles' database that is created by `tippecanoe`
        self.__mbtiles_file = os.path.join(self.__map_dir, 'index.mbtiles')

        self.__geojson_files = []
        self.__tippe_inputs = []
        self.__upload_files = []

        # Properties about map features
        self.__map_properties = JsonProperties(self.__manifest)

        self.__layer_dict = OrderedDict()
        self.__visible_layer_count = 0

        self.__annotations = {}
        self.__creator = 'mapmaker' ## FIX, add version info creator

        self.__map_area = None
        self.__extent = None
        self.__centre = None

        self.__last_feature_id = 0
        self.__class_to_feature = defaultdict(list)
        self.__id_to_feature = {}

    def __len__(self):
        return self.__visible_layer_count

    @property
    def extent(self):
        return self.__extent

    @property
    def id(self):
        return self.__id

    @property
    def layer_ids(self):
        return list(self.__layer_dict.keys())

    @property
    def map_directory(self):
        return self.__map_dir

    @property
    def map_properties(self):
        return self.__map_properties

    @property
    def models(self):
        return self.__models

    def make(self):
    #==============
        self.__begin_make()

        # Process flatmap's sources to create FeatureLayers
        self.__process_sources()

        if not settings.get('errorCheck', False):
            # Add high-resolution features showing details
            self.__add_details()
            # Set additional properties from properties file
            self.__set_feature_properties()
            # Generate metadata with connection information
            self.__resolve_paths()
            # Output all features (as GeoJSON)
            self.__output_geojson()
            # Generate vector tiles from GeoJSON
            self.__make_vector_tiles()
            # Generate image tiles
            if settings.get('backgroundTiles', False):
                self.__make_raster_tiles()
            # Save the flatmap's metadata
            self.__save_metadata()
            # Upload the generated map to a server
            if settings.get('uploadHost') is not None:
                self.__upload_map(settings.get('uploadHost'))

        # All done so clean up
        self.__finish_make()

    def __begin_make(self):
    #======================
        self.__geojson_files = []
        self.__tippe_inputs = []
        self.__upload_files = []

    def __finish_make(self):
    #=======================
        # Show what the map is about
        if self.models is not None:
            log('Generated map: {} for {}'.format(self.id, self.models))
        else:
            log('Generated map: {}'.format(self.id))
        ## FIX v's errorCheck
        for filename in self.__geojson_files:
            if settings.get('saveGeoJSON', False):
                print(filename)
            else:
                os.remove(filename)

    def __process_sources(self):
    #===========================
        tile_background = settings.get('backgroundTiles', False)
        # Sort so any ``base`` source kind is processed first
        for layer_number, source in enumerate(sorted(
                                        self.__manifest.sources,
                                        key=lambda source: source.get('kind'))):
            source_id = source.get('id')
            source_kind = source.get('kind')
            source_href = source.get('href')
            if source_kind == 'slides':
                source_layer = PowerpointSource(self, source_id, source_href,
                                                get_background=tile_background)
            elif source_kind == 'image':
                if layer_number > 0 and 'boundary' not in source:
                    raise ValueError('An image source must specify a boundary')
                source_layer = MBFSource(self, source_id, source_href,
                                         boundary_id=source.get('boundary'),
                                         output_layer=(layer_number==0))
            elif source_kind in ['base', 'details']:
                source_layer = SVGSource(self, source_id, source_href,
                                         output_layer=(source_kind=='base'))
            else:
                raise ValueError('Unsupported source kind: {}'.format(source_kind))

            source_layer.process()
            self.__add_source_layers(source_layer)

            # The first layer is used as the base map
            if layer_number == 0:
                if source_kind == 'details':
                    raise ValueError('Details layer cannot be the base map')
                self.__extent = source_layer.extent
                self.__centre = ((self.__extent[0] + self.__extent[2])/2,
                                 (self.__extent[1] + self.__extent[3])/2)
                self.__map_area = source_layer.map_area()
            elif source_kind not in ['details', 'image']:
                raise ValueError('Can only have a single base map')

        if self.__visible_layer_count == 0:
            raise ValueError('No map layers in sources...')

    def is_duplicate_feature_id(self, id):
    #=====================================
        return self.__id_to_feature.get(id, None) is not None

    def save_feature_id(self, feature):
    #==================================
        if feature.has_property('id'):
            self.__id_to_feature[feature.get_property('id')] = feature.feature_id
        if feature.has_property('class'):
            self.__class_to_feature[feature.get_property('class')].append(feature.feature_id)

    def new_feature(self, geometry, properties, has_children=False):
    #===============================================================
        self.__last_feature_id += 1
        return Feature(self.__last_feature_id, geometry, properties, has_children)

    def __add_layer(self, layer):
    #============================
        if layer.id in self.__layer_dict:
            raise KeyError('Duplicate layer id: {}'.format(layer.id))
        self.__layer_dict[layer.id] = layer
        if layer.output_layer:
            self.__visible_layer_count += 1

    def __add_source_layers(self, map_source):
    #=========================================
        for layer in map_source.layers:
            self.__add_layer(layer)
            if layer.output_layer:
                layer.add_raster_layer(layer.id, map_source.extent, map_source, self.__zoom[0])

    def __set_feature_properties(self):
    #==================================
        for layer in self.__layer_dict.values():
            layer.set_feature_properties(self.__map_properties)
            layer.add_nerve_details()

    def __add_details(self):
    #=======================
        # Add details of high-resolution features by adding a details layer
        # for features with details

        ## Need image layers...
        ##
        ## have Image of slide with outline image and outline's BBOX
        ## so can get Rect with just outline. Transform to match detail's feature.
        ##
        ## set layer.__image from slide when first making??
        ## Also want image layers scaled and with minzoom set...

        log('Adding details...')
        detail_layers = []
        for layer in self.__layer_dict.values():
            if layer.output_layer and layer.detail_features:
                detail_layer = FeatureLayer('{}_details'.format(layer.id), layer.source, output_layer=True)
                detail_layers.append(detail_layer)
                self.__add_detail_features(layer, detail_layer, layer.detail_features)
        for layer in detail_layers:
            self.__add_layer(layer)

## Put all this into 'features.py' as a function??
    def __new_detail_feature(self, layer_id, detail_layer, minzoom, geometry, properties):
    #=====================================================================================
        new_feature = self.new_feature(geometry, properties)
        new_feature.set_property('layer', layer_id)
        new_feature.set_property('minzoom', minzoom)
        if properties.get('type') == 'nerve':
            new_feature.set_property('type', 'nerve-section')
            new_feature.set_property('nerveId', feature.feature_id)  # Used in map viewer
            ## Need to link outline feature of nerve into paths through the nerve so it is highlighted
            ## when mouse over a path through the nerve
            new_feature.set_property('tile-layer', 'pathways')
        detail_layer.add_feature(new_feature)
        self.save_feature_id(new_feature)
        return new_feature

    def __add_detail_features(self, layer, detail_layer, lowres_features):
    #=====================================================================
        extra_details = []
        for feature in lowres_features:
            self.__map_properties.update_feature_properties(feature.properties)
            hires_layer_id = feature.get_property('details')
            hires_layer = self.__layer_dict.get(hires_layer_id)
            if hires_layer is None:
                print("Cannot find details' layer '{}'".format(feature.get_property('details')))
                continue
            boundary_feature = hires_layer.features_by_id.get(hires_layer.boundary_id)
            if boundary_feature is None:
                raise KeyError("Cannot find boundary of '{}' layer".format(hires_layer.id))

            # Calculate transformation to map source shapes to the destination

            # NOTE: We have no way of ensuring that the vertices of the source and destination rectangles
            #       align as intended. As a result, output features might be rotated by some multiple
            #       of 90 degrees.
            src = np.array(boundary_feature.geometry.minimum_rotated_rectangle.exterior.coords, dtype = "float32")[:-1]
            dst = np.array(feature.geometry.minimum_rotated_rectangle.exterior.coords, dtype = "float32")[:-1]
            transform = Transform(cv2.getPerspectiveTransform(src, dst))

            minzoom = feature.get_property('maxzoom') + 1
            if feature.get_property('type') != 'nerve':
                # Set the feature's geometry to that of the high-resolution outline
                feature.geometry = transform.transform_geometry(boundary_feature.geometry)
            else:                             # nerve
                feature.del_property('maxzoom')

            if hires_layer.source.raster_source is not None:
                extent = transform.transform_extent(hires_layer.source.extent)

                layer.add_raster_layer('{}_{}'.format(detail_layer.id, hires_layer.id),
                                        extent, hires_layer.source, minzoom,
                                        local_world_to_base=transform)

            # The detail layer gets a scaled copy of each high-resolution feature
            for hires_feature in hires_layer.features:
                new_feature = self.__new_detail_feature(layer.id, detail_layer, minzoom,
                                                        transform.transform_geometry(hires_feature.geometry),
                                                        hires_feature.properties)
                if new_feature.has_property('details'):
                    extra_details.append(new_feature)

        # If hires features that we've just added also have details then add them
        # to the detail layer
        if extra_details:
            self.__add_detail_features(layer, detail_layer, extra_details)

    def __make_raster_tiles(self):
    #============================
        log('Generating background tiles (may take a while...)')
        for layer in self.__layer_dict.values():
            for raster_layer in layer.raster_layers:
                tilemaker = RasterTileMaker(raster_layer, self.__map_dir, self.__zoom[1])
                raster_tile_file = tilemaker.make_tiles()
                self.__upload_files.append(raster_tile_file)

    def __make_vector_tiles(self, compressed=True):
    #==============================================
        # Generate Mapbox vector tiles
        if len(self.__tippe_inputs) == 0:
            raise ValueError('No selectable layers found...')

        log('Running tippecanoe...')
        tippe_command = ['tippecanoe',
                            '--force',
                            '--projection=EPSG:4326',
                            '--buffer=100',
                            '--minimum-zoom={}'.format(self.__zoom[0]),
                            '--maximum-zoom={}'.format(self.__zoom[1]),
                            '--no-tile-size-limit',
                            '--output={}'.format(self.__mbtiles_file),
                        ]
        if not compressed:
            tippe_command.append('--no-tile-compression')
        if settings.get('quiet', False):
            tippe_command.append('--quiet')
        tippe_command += list(["-L{}".format(json.dumps(input)) for input in self.__tippe_inputs])

        if settings.get('showTippe', False):
            print('  \\\n    '.join(tippe_command))
        subprocess.run(tippe_command)

        # `tippecanoe` uses the bounding box containing all features as the
        # map bounds, which is not the same as the extracted bounds, so update
        # the map's metadata
        tile_db = MBTiles(self.__mbtiles_file)
        tile_db.add_metadata(compressed=compressed)
        tile_db.update_metadata(center=','.join([str(x) for x in self.__centre]),
                                bounds=','.join([str(x) for x in self.__extent]))
        tile_db.execute("COMMIT")
        tile_db.close();
        self.__upload_files.append('index.mbtiles')

    def __layer_metadata(self):
    #==========================
        metadata = []
        for layer in self.__layer_dict.values():
            if layer.output_layer:
                map_layer = {
                    'id': layer.id,
                    'description': layer.description,
                    'queryable-nodes': layer.queryable_nodes,
                    'features': layer.feature_types,
                    'image-layers': [source.id for source in layer.raster_layers]
                }
## FIX ??               if layer.slide_id is not None:
## layer source v's map source v's spec info.
##                         map_layer['source'] = layer.slide_id
                metadata.append(map_layer)
        return metadata

    def __output_geojson(self):
    #==========================
        log('Outputting GeoJson features...')
        for layer in self.__layer_dict.values():
            if layer.output_layer:
                log('Layer:', layer.id)
                geojson_output = GeoJSONOutput(layer, self.__map_area, self.__map_dir)
                saved_layer = geojson_output.save(layer.features, settings.get('saveGeoJSON', False))
                for (layer_name, filename) in saved_layer.items():
                    self.__geojson_files.append(filename)
                    self.__tippe_inputs.append({
                        'file': filename,
                        'layer': layer_name,
                        'description': '{} -- {}'.format(layer.description, layer_name)
                    })
                self.__annotations.update(layer.annotations)

    def __resolve_paths(self):
    #=========================
        # Set feature ids of path components
        self.__map_properties.resolve_pathways(self.__id_to_feature, self.__class_to_feature)

    def __save_metadata(self):
    #=========================
        log('Creating index and style files...')
        tile_db = MBTiles(self.__mbtiles_file)

        # Save the name of the map's manifest file
        tile_db.add_metadata(source=self.__id) ## TEMP   ## FIX

        # What the map models
        if self.__models is not None:
            tile_db.add_metadata(describes=self.__models)
        # Save layer details in metadata
        tile_db.add_metadata(layers=json.dumps(self.__layer_metadata()))
        # Save pathway details in metadata
        tile_db.add_metadata(pathways=json.dumps(self.__map_properties.resolved_pathways))
        # Save annotations in metadata
        tile_db.add_metadata(annotations=json.dumps(self.__annotations))
        # Save command used to run mapmaker
        tile_db.add_metadata(created_by=self.__creator)
        # Save the maps creation time
        tile_db.add_metadata(created=datetime.datetime.utcnow().isoformat())
        # Commit updates to the database
        tile_db.execute("COMMIT")

#*        ## TODO: set ``layer.properties`` for annotations...
#*        ##update_RDF(options['map_base'], options['map_id'], source, annotations)

        # Get list of all image sources from all layers
        raster_layers = []
        for layer in self.__layer_dict.values():
            raster_layers.extend(layer.raster_layers)

        map_index = {
            'id': self.__id,
            'min-zoom': self.__zoom[0],
            'max-zoom': self.__zoom[1],
            'bounds': self.__extent,
            'version': FLATMAP_VERSION,
            'image_layer': len(raster_layers) > 0  ## For compatibility
        }
        if self.__models is not None:
            map_index['describes'] = self.__models
        # Create `index.json` for building a map in the viewer
        with open(os.path.join(self.__map_dir, 'index.json'), 'w') as output_file:
            json.dump(map_index, output_file)

        # Create style file
        metadata = tile_db.metadata()
        style_dict = MapStyle.style(raster_layers, metadata, self.__zoom)
        with open(os.path.join(self.__map_dir, 'style.json'), 'w') as output_file:
            json.dump(style_dict, output_file)

        # Create TileJSON file
        json_source = tile_json(self.__id, self.__zoom, self.__extent)
        with open(os.path.join(self.__map_dir, 'tilejson.json'), 'w') as output_file:
            json.dump(json_source, output_file)

        tile_db.close();
        self.__upload_files.extend(['index.json', 'style.json', 'tilejson.json'])

    def __upload_map(self, host):
    #============================
        upload = ' '.join([ '{}/{}'.format(self.__id, f) for f in self.__upload_files ])
        cmd_stream = os.popen('tar -C {} -c -z {} | ssh {} "tar -C /flatmaps -x -z"'
                             .format(self.__map_dir, upload, host))
        return cmd_stream.read()

#===============================================================================
