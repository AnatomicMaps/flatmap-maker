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

from . import FLATMAP_VERSION, __version__
from .utils import configure_logging, log, set_as_list

#===============================================================================

from .annotation import Annotator
from .exceptions import MakerException
from .flatmap import FlatMap, Manifest, SOURCE_DETAIL_KINDS
from . import knowledgebase

from .output.geojson import GeoJSONOutput
from .output.mbtiles import MBTiles
from .output.sparc_dataset import SparcDataset
from .output.styling import MapStyle
from .output.tilemaker import RasterTileMaker

from .settings import settings, MAP_KIND

from .sources import FCPowerpointSource, MBFSource, PowerpointSource, SVGSource
from .shapes.shapefilter import ShapeFilter

#===============================================================================

"""
If logging to a file (either the ``--log`` or ``logPath`` option has been given)
then copy the resulting log to the generated flatmap's directory with this name
"""
MAKER_LOG = 'mapmaker.log.json'

"""
If a file with this name exists in the map's output directory then the map
is in the process of being made
"""
MAKER_SENTINEL = '.map_making'

#===============================================================================

INVALID_PUBLISHING_OPTIONS = [
    'authoring',
    'id',
    'ignoreGit',
    'ignoreSckan',
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
        if (log_file := options.get('logFile')) is None:
            if (log_path := options.get('logPath')) is not None:
                log_file = os.path.join(log_path, f'{os.getpid()}.log.json')

        if options.get('silent', False) and log_file is None:
            raise ValueError('`--silent` option requires `--log LOG_FILE` to be given')
        self.__file_log = configure_logging(log_file,
            verbose=options.get('verbose', False),
            silent=options.get('silent', False),
            debug=options.get('debug', False))
        log.info('Mapmaker', version=__version__)

        # Default base output directory to ``./flatmaps``.
        if 'output' not in options:
            options['output'] = './flatmaps'

        # Check zoom settings are valid
        min_zoom = 0
        max_zoom = options.get('maxZoom', 10)
        max_raster_zoom = options.get('maxRasterZoom', max_zoom)

        initial_zoom = options.get('initialZoom', 4)
        if max_zoom < min_zoom or max_zoom > 15:
            raise ValueError('Max zoom must be between {} and 15'.format(min_zoom))
        if max_raster_zoom > max_zoom:
            raise ValueError(f'Max raster zoom cannot be greater than max zoom ({max_zoom})')
        if initial_zoom < min_zoom or initial_zoom > max_zoom:
            raise ValueError(f'Initial zoom cannot be greater than max zoom ({max_zoom})')
        self.__zoom = (min_zoom, max_zoom, initial_zoom)

        if options.get('publish'):
            # Check the given options are compatible with SDS publishing
            errors = False
            for option in INVALID_PUBLISHING_OPTIONS:
                if options.get(option):
                    log.warning('Option not allowed when publishing a dataset', option=option)
                    errors = True
            if errors:
                raise ValueError('Invalid parameters for dataset publishing')
            if options.get('backgroundTiles', False):
                log.info('Publishing as a dataset has set `--background-tiles`')
                options['backgroundTiles'] = True

        if options.get('backgroundTiles', False) and (cpu_count := os.cpu_count()) is not None and cpu_count < 2:
            raise ValueError('Cannot make background tiles on a single CPU system')

        # Check we have been given a map source and get our manifest
        if 'source' in options:
            self.__manifest = Manifest(options['source'], single_file=options.get('singleFile'),
                                                          id=options.get('id'),
                                                          ignore_git=options.get('authoring', False)
                                                                  or options.get('ignoreGit', False),
                                                          manifest=options.get('manifest'),
                                                          commit=options.get('commit'))
        else:
            raise ValueError('No source manifest specified')
        self.__id = self.__manifest.id
        if self.__id is None:
            raise ValueError('No id given for map')

        # Publishing requires a ``description.json``
        if options.get('publish') and self.__manifest.description is None:
            raise ValueError('The manifest must specify a JSON `description` file if publishing')

        # All set to go
        log.info('Making map', id=self.__id)

        # Make sure our top-level directory exists
        map_base = options.get('output')
        if not os.path.exists(map_base):
            os.makedirs(map_base)

        # This is set here in case we have to clean up early
        self.__geojson_files = []

        # Our source of knowledge, updated with information about maps we've made, held in a global place
        sckan_version = options.get('sckanVersion', self.__manifest.sckan_version)
        store_params = {
            'clean_connectivity': options.get('cleanConnectivity', False),
            'sckan_version': sckan_version,
            'sckan_provenance': True,
            'verbose': True
        }

        if len(self.__manifest.neuron_connectivity) == 0:
            options['ignoreSckan'] = True

        # Ignoring SCKAN implies accepting invalid neurons
        if options.get('ignoreSckan', False):
            options['invalidNeurons'] = True
            store_params.update({
                'use_sckan': False
            })

        # Save options to add to map's metadata
        self.__options = options

        # Save options into global ``settings`` dict
        settings.update(options)

        settings['KNOWLEDGE_STORE'] = knowledgebase.KnowledgeStore(map_base, **store_params)
        self.__sckan_provenance = knowledgebase.sckan_provenance()

        # Our ``uuid`` depends on the source Git repository commit,
        # the contents of the map's manifest, mapmaker's version,
        # and the version of SCKAN we use for connectivity.
        if (len(self.__sckan_provenance)
        and (repo := self.__manifest.git_repository) is not None):
            uuid_source = (repo.sha
                        + json.dumps(self.__manifest.raw_manifest, sort_keys=True)
                        + __version__
                        + json.dumps(self.__sckan_provenance, sort_keys=True))
            self.__uuid = str(uuid.uuid5(uuid.NAMESPACE_URL, uuid_source))
        else:
            self.__uuid = None

        # Where the generated map is saved
        self.__map_dir = os.path.join(map_base, self.__uuid if self.__uuid is not None else self.__id)

        if options.get('force', False):
            shutil.rmtree(self.__map_dir, True)

        self.__maker_sentinel = os.path.join(self.__map_dir, MAKER_SENTINEL)

        if os.path.exists(self.__map_dir):
            if os.path.exists(self.__maker_sentinel):
                self.__clean_up(remove_sentinel=False)
                raise MakerException('Last making of map failed -- use `--force` to re-make')
            log.info('Map already exists -- use `--force` to re-make', id=self.id, uuid=self.uuid, path=self.__map_dir)
            self.__clean_up()
            exit(0)
        else:
            os.makedirs(self.__map_dir)

        # Create an empty sentinel
        with open(self.__maker_sentinel, 'a'):
            pass

        # The vector tiles' database that is created by ``tippecanoe``
        self.__mbtiles_file = os.path.join(self.__map_dir, 'index.mbtiles')
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
    def sckan_provenance(self):
        return self.__sckan_provenance

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
                log.info('Saved SVG', svg=svg_file)

        # Create a Sparc dataset if publishing
        if (sds_output := settings.get('publish')) is not None:
            log.info('Generating SPARC dataset...', dataset=sds_output)
            sparc_dataset = SparcDataset(self.__flatmap)
            sparc_dataset.generate()
            sparc_dataset.save(sds_output)

        # Show what the map is about
        log_details = {'id': self.id, 'uuid': self.uuid, 'path': self.__map_dir}
        if self.__flatmap.models is not None:
            log_details['models'] = self.__flatmap.models
        log.info('Generated map', **log_details)

        # Tidy up
        self.__clean_up()

    def __begin_make(self):
    #======================
        # Initialise flatmap
        self.__flatmap.initialise()

        # Reinitialise lists we use
        self.__geojson_files = []
        self.__tippe_inputs = []

    def __clean_up(self, remove_sentinel=True):
    #==========================================
        # We are finished with the knowledge base
        settings['KNOWLEDGE_STORE'].close()

        # Remove any GeoJSON files (unless ``--save-geojson)
        for filename in self.__geojson_files:
            if settings.get('saveGeoJSON', False):
                print(filename)
            else:
                os.remove(filename)

        # Remove any temporary directory created for the map's sources
        self.__manifest.clean_up()

        if self.__file_log is not None:
            maker_log = os.path.join(self.__map_dir, MAKER_LOG)
            if not os.path.exists(maker_log):
                log_file = self.__file_log.baseFilename
                self.__file_log.close()
                with open(log_file, 'r') as log:
                    with open(os.path.join(self.__map_dir, MAKER_LOG), 'w') as fp:
                        fp.write(log.read())

        # All done, remove our sentinel
        if remove_sentinel and os.path.exists(self.__maker_sentinel):
            os.remove(self.__maker_sentinel)

    def __process_sources(self):
    #===========================
        if self.__flatmap.map_kind == MAP_KIND.FUNCTIONAL:
            self.__shape_filter = ShapeFilter()
        self.__processing_store = {}
        base_source = None
        for layer_number, source_manifest in enumerate(sorted(self.__manifest.sources,
                                                       # Make sure ``base`` and ``slides`` source kinds are processed first
                                                       key=lambda s: ('0' if s.kind in ['base', 'slides'] else '1') + s.kind)):
            id = source_manifest.id
            source_kind = source_manifest.kind
            href = source_manifest.href
            if self.__flatmap.map_kind == MAP_KIND.FUNCTIONAL:
                if href.endswith('.svg') or source_kind in SOURCE_DETAIL_KINDS:
                    try:
                        source = SVGSource(self.__flatmap, source_manifest)
                    except ValueError as err:
                        log.error(f'Source layer skipped', file=href, error=err)
                        continue
                elif source_kind in ['base', 'layer']:
                    source = FCPowerpointSource(self.__flatmap, source_manifest,
                                                shape_filter=self.__shape_filter,
                                                process_store=self.__processing_store)
                else:
                    raise ValueError(f'Unsupported FC kind: {source_kind}')
            elif source_kind == 'slides':
                source = PowerpointSource(self.__flatmap, source_manifest)
            elif source_kind == 'image':
                if layer_number > 0 and source_manifest.boundary is None:
                    raise ValueError('An image source must specify a boundary')
                source = MBFSource(self.__flatmap, source_manifest, exported=(layer_number==0))
            elif source_kind in ['base', 'detail', 'details']:
                source = SVGSource(self.__flatmap, source_manifest)
            else:
                raise ValueError(f'Unsupported source kind: {source_kind}')
            source.process()
            for (msg_kind, msg) in source.errors:
                if msg_kind == 'error':
                    log.error(msg)
                else:
                    log.warning(msg)
            self.__flatmap.add_source_layers(layer_number, source)
            if base_source is None and source_kind == 'base':
                base_source = source
        return base_source

    def __check_raster_tiles(self):
    #==============================
        log.info('Checking and making background tiles (may take a while...)')
        maker_processes = {}
        tilemakers = []
        for layer in self.__flatmap.layers:
            for raster_layer in layer.raster_layers:
                max_zoom = layer.max_zoom
                if layer.source.kind == 'base':
                    # maxRasterZoom is only for base maps
                    max_zoom = settings.get('maxRasterZoom', max_zoom)
                tilemaker = RasterTileMaker(raster_layer, self.__map_dir, max_zoom)
                tilemakers.append(tilemaker)
                if settings.get('backgroundTiles', False):
                    tilemaker_process = tilemaker.make_tiles()
                    tilemaker_process.start()
                    maker_processes[tilemaker_process.sentinel] = tilemaker_process
        while len(maker_processes) > 0:
            ended_processes = multiprocessing.connection.wait(maker_processes.keys(), 0.0001)
            for process in ended_processes:
                maker_processes.pop(process)
        for tilemaker in tilemakers:
            if tilemaker.have_tiles():
                self.__raster_layers.append(tilemaker.raster_layer)

    def __create_preview(self, source):
    #==================================
        log.info('Creating preview...')
        source.create_preview()

    def __make_vector_tiles(self, compressed=True):
    #==============================================
        # Generate Mapbox vector tiles
        if len(self.__tippe_inputs) == 0:
            raise ValueError('No vector tile layers found...')

        log.info('Running tippecanoe...')
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
        log.info('Outputting features...')
        exported_features = []
        feature_export_file = settings.get('exportFeatures', '')
        for layer in self.__flatmap.layers:
            if layer.exported:
                log.info('Map layer', layer=layer.id, feature_count=len(layer.features))
                if feature_export_file != '':
                    for feature in layer.features:
                        if (feature.id is not None
                        and not feature.get_property('exclude', False)
                        and feature.get_property('label', '') != ''
                        and (not 'error' in feature.properties) or settings.get('authoring', False)):
                            exported_features.append(feature)
                geojson_output = GeoJSONOutput(self.__flatmap, layer, self.__map_dir)
                saved_layer = geojson_output.save(layer.features, settings.get('saveGeoJSON', False))
                for (layer_name, filename) in saved_layer.items():
                    self.__geojson_files.append(filename)
                    self.__tippe_inputs.append({
                        'file': filename,
                        'layer': layer_name,
                        'description': '{} -- {}'.format(layer.description, layer_name)
                    })
                self.__flatmap.update_annotations(layer.annotations)
        if feature_export_file != '':
            def clean_export(entry: dict):
                if entry['models'] is None:
                    entry.pop('models')
                return entry
            export = list(map(clean_export, [{
                'id': feature.id,
                'models': feature.models,
                'label': feature.get_property('label')
            } for feature in exported_features]))
            with open(feature_export_file, 'w') as fp:
                fp.write(json.dumps(export, indent=4))

    def __save_metadata(self):
    #=========================
        log.info('Creating index and style files...')
        tile_db = MBTiles(self.__mbtiles_file)

        # Save flatmap's metadata, including settings used to generate map
        metadata = self.__flatmap.metadata
        metadata['settings'] = self.__options
        if (git_status := self.__manifest.git_status) is not None:
            metadata['git-status'] = git_status
            metadata['git-status']['committed'] = metadata['git-status']['committed'].isoformat(timespec='milliseconds')
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
        settings['KNOWLEDGE_STORE'].add_flatmap(self.__flatmap, self.__sckan_provenance.get('knowledge-source'))

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
        if self.__flatmap.map_kind == MAP_KIND.FUNCTIONAL:
            map_index['style'] = 'functional'
        elif self.__flatmap.map_kind == MAP_KIND.CENTRELINE:
            map_index['style'] = 'centreline'
        else:
            map_index['style'] = 'anatomical'
        if git_status is not None:
            map_index['git-status'] = git_status
        if len(self.__sckan_provenance):
            map_index['connectivity'] = self.__sckan_provenance

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
