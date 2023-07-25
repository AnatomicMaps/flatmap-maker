#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2023  David Brooks
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

import json
import os
import pathlib
import multiprocessing.connection
import shutil
import subprocess
import uuid

#===============================================================================

from mapmaker import FLATMAP_VERSION, __version__
from mapmaker.utils import configure_logging, log, set_as_list

#===============================================================================

from .annotation import Annotator
from .flatmap import FlatMap, Manifest
from . import knowledgebase

from .output.geojson import GeoJSONOutput
from .output.mbtiles import MBTiles
from .output.sparc_dataset import SparcDataset
from .output.styling import MapStyle
from .output.tilemaker import RasterTileMaker

from .settings import settings

from .sources import FCPowerpointSource, MBFSource, PowerpointSource, SVGSource
from .sources.shapefilter import ShapeFilter

#===============================================================================

INVALID_PUBLISHING_OPTIONS = [
    'authoring',
    'id',
    'ignoreGit',
    'invalidNeurons',
    'sckanVersion',
    'singleFile',
]

#===============================================================================

class MapMaker(object):
    def __init__(self, options):
        # ``silent`` implies not ``verbose``
        if options.get('silent', False):
            options['verbose'] = False

        if options.get('sckanVersion') is not None and not options.get('ignoreGit', False):
            raise ValueError('`--ignore-git` must be set when `--sckan-version` is used')

        # Setup logging

        log_file = options.get('logFile')
        if log_file is None:
            log_path = options.get('logPath')
            if log_path is not None:
                log_file = os.path.join(log_path, '{}.log'.format(os.getpid()))
        if options.get('silent', False) and log_file is None:
            raise ValueError('`--silent` option requires `--log LOG_FILE` to be given')
        configure_logging(log_file,
            verbose=options.get('verbose', False),
            silent=options.get('silent', False),
            debug=options.get('debug', False))
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

        if options.get('publish'):
            # Check the given options are compatible with SDS publishing
            errors = False
            for option in INVALID_PUBLISHING_OPTIONS:
                if options.get(option):
                    log.warning(f'`{option}` not allowed when publishing a dataset')
                    errors = True
            if errors:
                raise ValueError('Invalid parameters for dataset publishing ')
            options['backgroundTiles'] = True

        # Authoring implies to clean output directory, report deprecated markup, and don't tile background
        if options.get('authoring', False):
            options['showDeprecated'] = True

        # Save options to add to map's metadata
        self.__options = options

        # Save options into global ``settings`` dict
        settings.update(options)

        # Check we have been given a map source and get our manifest
        if 'source' in options:
            self.__manifest = Manifest(options['source'], single_file=options.get('singleFile'), id=options.get('id'),
                                                          ignore_git=settings.get('authoring', False)
                                                                  or settings.get('ignoreGit', False))
        else:
            raise ValueError('No source manifest specified')
        self.__id = self.__manifest.id
        if self.__id is None:
            raise ValueError('No id given for map')

        # Publishing requires a ``description.json``
        if options.get('publish') and self.__manifest.description is None:
            raise ValueError('The manifest must specify a JSON `description` file if publishing')

        # All set to go
        log('Making map: {}'.format(self.__id))

        # Make sure our output directories exist
        map_base = options.get('output')
        if not os.path.exists(map_base):
            os.makedirs(map_base)

        # Our source of knowledge, updated with information about maps we've made, held in a global place
        sckan_version = settings.get('sckanVersion', self.__manifest.sckan_version)
        knowledge_store = knowledgebase.KnowledgeStore(map_base,
                                         clean_connectivity=settings.get('cleanConnectivity', False),
                                         sckan_version=sckan_version)
        settings['KNOWLEDGE_STORE'] = knowledge_store

        self.__sckan_build = knowledgebase.sckan_build()

        # Our ``uuid`` depends on the source Git repository commit,
        # the contents of the map's manifest, mapmaker's version,
        # and the version of SCKAN we use for connectivity.
        if (self.__sckan_build is not None
        and (repo := self.__manifest.git_repository) is not None):
            self.__uuid = str(uuid.uuid5(uuid.NAMESPACE_URL,
                              repo.sha
                            + json.dumps(self.__manifest.manifest)
                            + __version__
                            + self.__sckan_build['created']))
        else:
            self.__uuid = None

        # Where the generated map is saved
        self.__map_dir = os.path.join(map_base, self.__uuid if self.__uuid is not None else self.__id)
        if options.get('clean', False):
            shutil.rmtree(self.__map_dir, True)
        if not os.path.exists(self.__map_dir):
            os.makedirs(self.__map_dir)

        # The vector tiles' database that is created by `tippecanoe`
        self.__mbtiles_file = os.path.join(self.__map_dir, 'index.mbtiles')
        self.__geojson_files = []
        self.__tippe_inputs = []

        # Raster tile layers
        self.__raster_layers = []

        # Exclude shapes from a layer if they are in the base layer (FC maps)
        self.__shape_filter = None

        # An annotator (for functional connectivity)
        if self.__manifest.annotation is not None:
            self.__annotator = Annotator(self.__manifest.annotation)
        else:
            self.__annotator = None

        # The map we are making
        self.__flatmap = FlatMap(self.__manifest, self, self.__annotator)

    @property
    def id(self):
        return self.__id

    @property
    def map_dir(self):
        return self.__map_dir

    @property
    def uuid(self):
        return self.__uuid

    @property
    def zoom(self):
        return self.__zoom

    def make(self):
    #==============
        self.__begin_make()

        # Process flatmap's sources to create MapLayers
        base_source = self.__process_sources()

        # Finish flatmap processing (path routing, etc)
        self.__flatmap.close()

        # Do we have any map layers?
        if len(self.__flatmap) == 0:
            raise ValueError('No map layers in sources...')

        # Save annotation
        if self.__annotator is not None:
            self.__annotator.save()

        # Output all features (as GeoJSON) and optionally, their identifiers
        self.__output_features()

        # Generate vector tiles from GeoJSON
        self.__make_vector_tiles()

        # Generate image tiles as required
        self.__check_raster_tiles()

        # Save an SVG preview in the output directory
        if base_source is not None:
            self.__create_preview(base_source)

        # Save the flatmap's metadata
        self.__save_metadata()

        # All done so clean up
        self.__finish_make()

    def __begin_make(self):
    #======================
        # Initialise flatmap
        self.__flatmap.initialise()

        # Reinitialise lists we use
        self.__geojson_files = []
        self.__tippe_inputs = []

    def __finish_make(self):
    #=======================
        # We are finished with the knowledge base
        settings['KNOWLEDGE_STORE'].close()

        # Write out details of FC neurons if option set
        if (export_file := settings.get('exportNeurons')) is not None:
            with open(export_file, 'w') as fp:
                fp.write(json.dumps(self.__flatmap.sckan_neuron_populations.neurons_with_evidence(), indent=4))

        if ((svg_export_file := settings.get('exportSVG')) is not None
         and 'svg-maker' in self.__processing_store):
            svg_maker = self.__processing_store['svg-maker']
            svg_file = pathlib.Path(svg_export_file).with_suffix('.svg')
            with open(svg_file, 'w') as fp:
                svg_maker.save(fp)
                log.info(f'Saved SVG as {svg_file}')

        # Create a Sparc dataset if publishing
        if (sds_output := settings.get('publish')) is not None:
            log(f'Generating SPARC dataset {sds_output}...')
            sparc_dataset = SparcDataset(self.__manifest, self.__flatmap)
            sparc_dataset.generate()
            sparc_dataset.save(sds_output)

        # Show what the map is about
        if self.__flatmap.models is not None:
            log(f'Generated map: id: {self.id}, uuid: {self.uuid}, models: {self.__flatmap.models}, output: {self.__map_dir}')
        else:
            log(f'Generated map: id: {self.id}, uuid: {self.uuid}, output: {self.__map_dir}')

        for filename in self.__geojson_files:
            if settings.get('saveGeoJSON', False):
                print(filename)
            else:
                os.remove(filename)

    def __process_sources(self):
    #===========================
        # Make sure ``base`` and ``slides`` source kinds are processed first
        def kind_order(source):
            kind = source.get('kind', '')
            return ('0' if kind in ['base', 'slides'] else '1') + kind
        # Make sure any source range is a list of int
        def get_range(source_range):
            if source_range is not None:
                if isinstance(source_range, list):
                    return [int(n) for n in source_range]
                else:
                    return [int(source_range)]

        if self.__manifest.kind == 'functional':
            settings['functionalConnectivity'] = True
            self.__shape_filter = ShapeFilter()
        else:
            settings['functionalConnectivity'] = False
        self.__processing_store = {}
        base_source = None
        for layer_number, manifest_source in enumerate(sorted(self.__manifest.sources, key=kind_order)):
            id = manifest_source.get('id')
            kind = manifest_source.get('kind')
            href = manifest_source['href']
            if settings['functionalConnectivity']:
                if kind in ['base', 'layer']:
                    source = FCPowerpointSource(self.__flatmap, id, href,
                                                kind=kind,
                                                source_range=get_range(manifest_source.get('slides')),
                                                shape_filter=self.__shape_filter,
                                                process_store=self.__processing_store)
                else:
                    raise ValueError('Unsupported FC kind: {}'.format(kind))
            elif kind == 'slides':
                source = PowerpointSource(self.__flatmap, id, href,
                                    source_range=get_range(manifest_source.get('slides')))
            elif kind == 'image':
                if layer_number > 0 and 'boundary' not in manifest_source:
                    raise ValueError('An image source must specify a boundary')
                source = MBFSource(self.__flatmap, id, href,
                                   boundary_id=manifest_source.get('boundary'),
                                   exported=(layer_number==0))
            elif kind in ['base', 'details']:
                source = SVGSource(self.__flatmap, id, href, kind)
            else:
                raise ValueError('Unsupported source kind: {}'.format(kind))
            source.process()
            for (kind, msg) in source.errors:
                if kind == 'error':
                    log.error(msg)
                else:
                    log.warning(msg)
            self.__flatmap.add_source_layers(layer_number, source)
            if base_source is None and kind == 'base':
                base_source = source
        return base_source

    def __check_raster_tiles(self):
    #==============================
        log('Checking and making background tiles (may take a while...)')
        maker_processes = {}
        tilemakers = []
        for layer in self.__flatmap.layers:
            for raster_layer in layer.raster_layers:
                tilemaker = RasterTileMaker(raster_layer, self.__map_dir, self.__zoom[1])
                tilemakers.append(tilemaker)
                if settings.get('backgroundTiles', False):
                    tilemaker_process = tilemaker.make_tiles()
                    tilemaker_process.start()
                    maker_processes[tilemaker_process.sentinel] = tilemaker_process
        while len(maker_processes) > 0:
            ended_processes = multiprocessing.connection.wait(maker_processes.keys())
            for process in ended_processes:
                maker_processes.pop(process)
        for tilemaker in tilemakers:
            if tilemaker.have_tiles():
                self.__raster_layers.append(tilemaker.raster_layer)

    def __create_preview(self, source):
    #==================================
        log('Creating preview...')
        source.create_preview()

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
        tile_db.add_metadata(center=','.join([str(x) for x in self.__flatmap.centre]),      # type: ignore
                             bounds=','.join([str(x) for x in self.__flatmap.extent]))      # type: ignore
        tile_db.execute("COMMIT")
        tile_db.close();

    def __output_features(self):
    #===========================
        log('Outputting features...')
        exported_features = []
        identifier_export = settings.get('exportIdentifiers', '')
        for layer in self.__flatmap.layers:
            if layer.exported:
                log('Layer: {}'.format(layer.id))
                if identifier_export != '':
                    for feature in layer.features:
                        if (feature.id is not None
                        and feature.models is not None
                        and not feature.get_property('exclude', False)
                        and (not 'error' in feature.properties) or settings.get('authoring', False)):
                            exported_features.append(feature)
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
        if identifier_export != '':
            export = [{
                'id': feature.id,
                'term': feature.models,
                'label': feature.get_property('label', '')
            } for feature in exported_features]
            with open(identifier_export, 'w') as fp:
                fp.write(json.dumps(export, indent=4))

    def __save_metadata(self):
    #=========================
        log('Creating index and style files...')
        tile_db = MBTiles(self.__mbtiles_file)

        # Save flatmap's metadata, including settings used to generate map
        metadata = self.__flatmap.metadata
        metadata['settings'] = self.__options
        if (git_status := self.__manifest.git_status) is not None:
            metadata['git-status'] = git_status
        if self.__sckan_build is not None:
            metadata['sckan'] = self.__sckan_build
        tile_db.add_metadata(metadata=json.dumps(metadata))

        # Save layer details in metadata
        tile_db.add_metadata(layers=json.dumps(self.__flatmap.layer_metadata()))
        # Save pathway details in metadata
        tile_db.add_metadata(pathways=json.dumps(self.__flatmap.connectivity()))
        # Save annotations in metadata
        tile_db.add_metadata(annotations=json.dumps(self.__flatmap.annotations, default=set_as_list))

        # Commit updates to the database
        tile_db.execute("COMMIT")

        # Update our knowledge base
        settings['KNOWLEDGE_STORE'].add_flatmap(self.__flatmap)

#*        ## TODO: set ``layer.properties`` for annotations...
#*        ##update_RDF(options['map_base'], options['map_id'], source, annotations)

        map_index = {
            'id': self.__id,
            'source': self.__manifest.url,
            'min-zoom': self.__zoom[0],
            'max-zoom': self.__zoom[1],
            'bounds': self.__flatmap.extent,
            'version': FLATMAP_VERSION,
            'image-layers': len(self.__raster_layers) > 0
        }
        if self.__uuid is not None:
            map_index['uuid'] = self.__uuid
        if self.__flatmap.models is not None:
            map_index['taxon'] = self.__flatmap.models
        if self.__manifest.biological_sex is not None:
            map_index['biologicalSex'] = self.__manifest.biological_sex
        map_index['authoring'] = settings.get('authoring', False)
        if settings.get('functionalConnectivity', False):
            map_index['style'] = 'functional'
        else:
            map_index['style'] = 'anatomical'
        if git_status is not None:
            map_index['git-status'] = git_status
        if self.__sckan_build is not None:
            map_index['sckan'] = self.__sckan_build['created']

        # Create `index.json` for building a map in the viewer
        with open(os.path.join(self.__map_dir, 'index.json'), 'w') as output_file:
            json.dump(map_index, output_file)

        # Create style file
        metadata = tile_db.metadata()
        style_dict = MapStyle.style(self.__raster_layers, metadata, self.__zoom)
        with open(os.path.join(self.__map_dir, 'style.json'), 'w') as output_file:
            json.dump(style_dict, output_file)

        tile_db.close();

#===============================================================================
