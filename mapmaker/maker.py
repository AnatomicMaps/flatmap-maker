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

import datetime
import json
import os
import pathlib
import shutil
import subprocess
import sys
from urllib.parse import urljoin

#===============================================================================

from mapmaker import FLATMAP_VERSION, __version__
from mapmaker.utils import configure_logging, log, FilePath

#===============================================================================

from .flatmap import FlatMap

from .knowledgebase import LabelDatabase

from .output.geojson import GeoJSONOutput
from .output.mbtiles import MBTiles
from .output.styling import MapStyle
from .output.tilejson import tile_json
from .output.tilemaker import RasterTileMaker

from .settings import settings

from .sources import MBFSource, PowerpointSource, SVGSource

#===============================================================================

class Manifest(object):
    def __init__(self, manifest_path):
        path = FilePath(manifest_path)
        self.__url = path.url
        self.__manifest = path.get_json()
        if 'id' not in self.__manifest:
            raise ValueError('No id given for manifest')
        if 'sources' not in self.__manifest:
            raise ValueError('No sources given for manifest')
        if 'anatomicalMap' in self.__manifest:
            self.__manifest['anatomicalMap'] = urljoin(self.__url, self.__manifest['anatomicalMap'])
        if 'properties' in self.__manifest:
            self.__manifest['properties'] = urljoin(self.__url, self.__manifest['properties'])
        if 'somaProcesses' in self.__manifest:
            self.__manifest['somaProcesses']['href'] = urljoin(self.__url, self.__manifest['somaProcesses']['href'])
        self.__connectivity = []
        for path in self.__manifest.get('connectivity', []):
            self.__connectivity.append(urljoin(self.__url, path))
        for source in self.__manifest['sources']:
            source['href'] = urljoin(self.__url, source['href'])

    @property
    def anatomical_map(self):
        return self.__manifest.get('anatomicalMap')

    @property
    def id(self):
        return self.__manifest['id']

    @property
    def models(self):
        return self.__manifest.get('models')

    @property
    def connectivity(self):
        return self.__connectivity

    @property
    def properties(self):
        return self.__manifest.get('properties')

    @property
    def soma_processes(self):
        return self.__manifest.get('somaProcesses')

    @property
    def sources(self):
        return self.__manifest['sources']

    @property
    def url(self):
        return self.__url

#===============================================================================

class MapMaker(object):
    def __init__(self, options):
        # ``silent`` implies not ``verbose``
        if options.get('silent', False):
            options['verbose'] = False

        # Setup logging

        log_file = options.get('logFile')
        if log_file is None:
            log_path = options.get('logPath')
            if log_path is not None:
                log_file = os.path.join(log_path, '{}.log'.format(os.getpid()))
        configure_logging(log_file,
            verbose=options.get('verbose', False),
            silent=options.get('silent', False))
        log('Mapmaker {}'.format(__version__))

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

        # Check we have been given a map source and get our manifest
        if 'source' in options:
            self.__manifest = Manifest(options['source'])
        else:
            raise ValueError('No source manifest specified')
        self.__id = options.get('id', self.__manifest.id)
        if self.__id is None:
            raise ValueError('No id given for map')
        log('Making map: {}'.format(self.__id))

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

        # The map we are making
        self.__flatmap = FlatMap(self)

    @property
    def id(self):
        return self.__id

    @property
    def manifest(self):
        return self.__manifest

    @property
    def zoom(self):
        return self.__zoom

    def make(self):
    #==============
        self.__begin_make()

        # Process flatmap's sources to create MapLayers
        self.__process_sources()

        if not settings.get('errorCheck', False):
            # Finish off flatmap
            self.__flatmap.close()
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
        if self.__flatmap.models is not None:
            log('Generated map: {} for {}'.format(self.id, self.__flatmap.models))
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
        # Make sure ``base`` and ``slides`` source kinds are processed first
        def kind_order(source):
            kind = source.get('kind', '')
            return ('0' if kind in ['base', 'slides'] else '1') + kind
        for layer_number, source in enumerate(sorted(self.__manifest.sources, key=kind_order)):
            id = source.get('id')
            kind = source.get('kind')
            href = source['href']
            if kind == 'slides':
                source_layer = PowerpointSource(self.__flatmap, id, href,
                                                get_background=tile_background)
            elif kind == 'image':
                if layer_number > 0 and 'boundary' not in source:
                    raise ValueError('An image source must specify a boundary')
                source_layer = MBFSource(self.__flatmap, id, href,
                                         boundary_id=source.get('boundary'),
                                         exported=(layer_number==0))
            elif kind in ['base', 'details']:
                source_layer = SVGSource(self.__flatmap, id, href, kind)
            else:
                raise ValueError('Unsupported source kind: {}'.format(kind))
            source_layer.process()
            for (kind, msg) in source_layer.errors:
                if kind == 'error':
                    log.error(msg)
                else:
                    log.warn(msg)
            self.__flatmap.add_source_layers(layer_number, source_layer)
        if len(self.__flatmap) == 0:
            raise ValueError('No map layers in sources...')

    def __make_raster_tiles(self):
    #============================
        log('Generating background tiles (may take a while...)')
        for layer in self.__flatmap.layers:
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
        if not settings.get('verbose', True):
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
        tile_db.add_metadata(center=','.join([str(x) for x in self.__flatmap.centre]),
                             bounds=','.join([str(x) for x in self.__flatmap.extent]))
        tile_db.execute("COMMIT")
        tile_db.close();
        self.__upload_files.append('index.mbtiles')

    def __output_geojson(self):
    #==========================
        log('Outputting GeoJson features...')
        for layer in self.__flatmap.layers:
            if layer.exported:
                log('Layer: {}'.format(layer.id))
                geojson_output = GeoJSONOutput(layer, self.__flatmap.area, self.__map_dir)
                saved_layer = geojson_output.save(layer.features, settings.get('saveGeoJSON', False))
                for (layer_name, filename) in saved_layer.items():
                    self.__geojson_files.append(filename)
                    self.__tippe_inputs.append({
                        'file': filename,
                        'layer': layer_name,
                        'description': '{} -- {}'.format(layer.description, layer_name)
                    })
                self.__flatmap.update_annotations(layer.annotations)

    def __save_metadata(self):
    #=========================
        log('Creating index and style files...')
        tile_db = MBTiles(self.__mbtiles_file)

        metadata = {
            # The maps creation time
            'created': datetime.datetime.utcnow().isoformat(),
            # Who made the map
            'creator': 'mapmaker {}'.format(__version__),
            # The URL of the map's manifest
            'source': self.__manifest.url,
            'version': FLATMAP_VERSION
        }
        # What the map models
        if self.__flatmap.models is not None:
            metadata['describes'] = self.__flatmap.models

        # Save flatmap's metadata
        tile_db.add_metadata(metadata=json.dumps(metadata))
        ## Backwards compatibility...
        # NB: we need to set version and if newer just save with name `metadata`
        # The map server needs to recognise the new way of doing things...
        tile_db.add_metadata(**metadata)

        # Save layer details in metadata
        tile_db.add_metadata(layers=json.dumps(self.__flatmap.layer_metadata()))
        # Save pathway details in metadata
        tile_db.add_metadata(pathways=json.dumps(self.__flatmap.pathways()))
        # Save annotations in metadata
        tile_db.add_metadata(annotations=json.dumps(self.__flatmap.annotations))

        # Commit updates to the database
        tile_db.execute("COMMIT")

#*        ## TODO: set ``layer.properties`` for annotations...
#*        ##update_RDF(options['map_base'], options['map_id'], source, annotations)

        # Get list of all image sources from all layers
        raster_layers = []
        for layer in self.__flatmap.layers:
            raster_layers.extend(layer.raster_layers)

        map_index = {
            'id': self.__id,
            'source': self.__manifest.url,
            'min-zoom': self.__zoom[0],
            'max-zoom': self.__zoom[1],
            'bounds': self.__flatmap.extent,
            'version': FLATMAP_VERSION,
            'image_layer': len(raster_layers) > 0  ## For compatibility
        }
        if self.__flatmap.models is not None:
            map_index['describes'] = self.__flatmap.models
        # Create `index.json` for building a map in the viewer
        with open(os.path.join(self.__map_dir, 'index.json'), 'w') as output_file:
            json.dump(map_index, output_file)

        # Create style file
        metadata = tile_db.metadata()
        style_dict = MapStyle.style(raster_layers, metadata, self.__zoom)
        with open(os.path.join(self.__map_dir, 'style.json'), 'w') as output_file:
            json.dump(style_dict, output_file)

        # Create TileJSON file
        json_source = tile_json(self.__id, self.__zoom, self.__flatmap.extent)
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
