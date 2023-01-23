#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2022  David Brooks
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

from __future__ import annotations
from enum import Enum
import json
import os
import pathlib
import multiprocessing.connection
import shutil
import subprocess
from typing import Optional
import uuid
from urllib.parse import urljoin

#===============================================================================

import git
import giturlparse

#===============================================================================

from mapmaker import FLATMAP_VERSION, __version__
from mapmaker.utils import configure_logging, log, FilePath

#===============================================================================

from .annotation import create_annotator
from .flatmap import FlatMap
from .knowledgebase import KnowledgeStore

from .output.geojson import GeoJSONOutput
from .output.mbtiles import MBTiles
from .output.styling import MapStyle
from .output.tilemaker import RasterTileMaker

from .settings import settings

from .sources import FCPowerpointSource, MBFSource, PowerpointSource, SVGSource
from .sources.fc_powerpoint import ShapeFilters as FCShapeFilters

#===============================================================================

UPSTREAM_MAP_REPOSITORIES = 'https://github.com/AnatomicMaps/'

#===============================================================================

class GitState(Enum):
    UNKNOWN   = 0
    DONTCARE  = 1
    STAGED    = 2
    CHANGED   = 3
    UNTRACKED = 4

#===============================================================================

class MapRepository:
    def __init__(self, working_dir: pathlib.Path):
        try:
            self.__repo = git.Repo(working_dir)
            self.__repo_path = pathlib.Path(os.path.abspath(working_dir))
            self.__changed_items = [ item.a_path for item in self.__repo.index.diff(None) ]
            self.__staged_items = [ item.a_path for item in self.__repo.index.diff('HEAD') ]
            self.__untracked_files = self.__repo.untracked_files
            self.__set_upstream_base()
        except git.InvalidGitRepositoryError:
            self.__repo = None
            if not settings.get('authoring', False):
                log.error('Flatmap sources must be in a git managed directory')

    @property
    def remotes(self) -> Optional[dict[str, str]]:
        return {
            remote.name: giturlparse.parse(remote.url).url2https
                for remote in self.__repo.remotes
            } if self.__repo is not None else None

    @property
    def sha(self) -> Optional[str]:
        return self.__repo.head.commit.hexsha if self.__repo is not None else None

    def __git_path(self, path):
        if self.__repo is not None:
            if path.startswith('file://'):
                path = path[7:]
            full_path = pathlib.Path(os.path.abspath(path))
            if full_path.is_relative_to(self.__repo_path):
                return str(full_path.relative_to(self.__repo_path))

    def __set_upstream_base(self) -> Optional[str]:
        if self.__repo is not None:
            upstream_url = None
            for remote in self.__repo.remotes:
                url = giturlparse.parse(remote.url).url2https
                if upstream_url is None:
                    upstream_url = url
                elif url.startswith(UPSTREAM_MAP_REPOSITORIES):
                    upstream_url = url
                    break
            url = giturlparse.parse(upstream_url)
            raw_folder = ('blob/' if url.host.endswith('github.com') else
                          'rawfile/' if url.host.endswith('physiomeproject.org') else
                          '')
            self.__upstream_base = f'{url.protocol}://{url.host}{url.port}/{url.owner}/{url.repo}/{raw_folder}{self.__repo.head.commit.hexsha}/'

    def status(self, path: str) -> GitState:
    #=======================================
        if self.__repo is not None:
            if (git_path := self.__git_path(path)) is not None:
                return (GitState.UNTRACKED if git_path in self.__untracked_files else
                        GitState.CHANGED if git_path in self.__changed_items else
                        GitState.STAGED if git_path in self.__staged_items else
                        GitState.DONTCARE)
            elif not settings.get('authoring', False):
                log.error(f"{path} is not under git control in the manifest's directory")
        return GitState.UNKNOWN

    def path_blob_url(self, path):
    #=============================
        if (git_path := self.__git_path(path)) is not None:
            return urljoin(self.__upstream_base, git_path)

#===============================================================================

class Manifest:
    def __init__(self, manifest_path, single_file=None, id=None):
        self.__path = FilePath(manifest_path)
        self.__repo = MapRepository(pathlib.Path(manifest_path).parent)
        self.__url = self.__path.url
        self.__connections = {}
        self.__connectivity = []
        self.__neuron_connectivity = []
        self.__uncommitted = 0

        if single_file is not None:
            # A special case is to make a map from a standalone source file
            if id is None:
                id = self.__url.rsplit('/', 1)[-1].rsplit('.', 1)[0].replace('_', '-').replace(' ', '_')
            self.__manifest = {
                'id': id,
                'sources': [
                    {
                        'id': id,
                        'href': self.__url,
                        'kind': 'base' if single_file == 'svg' else single_file
                    }
                ]
            }
        else:
            # Check the manifest itself is committed into the repository
            self.__check_committed(self.__url)

            self.__manifest = self.__path.get_json()
            if id is not None:
                self.__manifest['id'] = id
            elif 'id' not in self.__manifest:
                raise ValueError('No id given for manifest')

            if self.__manifest.get('sckan-version', 'production') not in ['production', 'staging']:
                raise ValueError("'sckan-version' in manifest must be `production' or 'staging'")
            for model in self.__manifest.get('neuronConnectivity', []):
                self.__neuron_connectivity.append(model)

            if 'sources' not in self.__manifest:
                raise ValueError('No sources given for manifest')
            for source in self.__manifest['sources']:
                source['href'] = self.__check_and_normalise_path(source['href'])
            if 'anatomicalMap' in self.__manifest:
                self.__manifest['anatomicalMap'] = self.__check_and_normalise_path(self.__manifest['anatomicalMap'])
            if 'annotation' in self.__manifest:
                self.__manifest['annotation'] = self.__check_and_normalise_path(self.__manifest['annotation'])
            if 'connectivityTerms' in self.__manifest:
                self.__manifest['connectivityTerms'] = self.__check_and_normalise_path(self.__manifest['connectivityTerms'])
            if 'properties' in self.__manifest:
                self.__manifest['properties'] = self.__check_and_normalise_path(self.__manifest['properties'])
            for path in self.__manifest.get('connectivity', []):
                self.__connectivity.append(self.__check_and_normalise_path(path))
            if self.__uncommitted:
                raise TypeError("Not all of the flatmap's sources are commited into git ('--authoring' option intended?)")

    @property
    def anatomical_map(self):
        return self.__manifest.get('anatomicalMap')

    @property
    def annotation(self):
        return self.__manifest.get('annotation')

    @property
    def biological_sex(self):
        return self.__manifest.get('biological-sex')

    @property
    def connections(self):
        return self.__connections

    @property
    def connectivity(self):
        return self.__connectivity

    @property
    def connectivity_terms(self):
        return self.__manifest.get('connectivityTerms')

    @property
    def git_status(self):
        if self.__repo.sha is not None:
            return {
                'sha': self.__repo.sha,
                'remotes': self.__repo.remotes
            }

    @property
    def id(self):
        return self.__manifest['id']

    @property
    def kind(self):
        return self.__manifest.get('kind', 'anatomical')

    @property
    def models(self):
        return self.__manifest.get('models')

    @property
    def neuron_connectivity(self):
        return self.__neuron_connectivity

    @property
    def properties(self):
        return self.__manifest.get('properties')

    @property
    def sckan_version(self):
        return self.__manifest.get('sckan-version', 'production')

    @property
    def sources(self):
        return self.__manifest['sources']

    @property
    def url(self):
        blob_url = self.__repo.path_blob_url(self.__url)
        return self.__url if blob_url is None else blob_url

    @property
    def uuid(self):
        return str(uuid.uuid5(uuid.NAMESPACE_URL, self.url))

    def __check_and_normalise_path(self, path) -> str:
    #=================================================
        normalised_path = self.__path.join_url(path)
        self.__check_committed(normalised_path)
        return normalised_path

    def __check_committed(self, path):
    #=================================
        if not settings.get('authoring', False):
            git_state = self.__repo.status(path)
            if git_state != GitState.DONTCARE:
                message = ('unknown to git' if git_state == GitState.UNKNOWN else
                           'staged to be committed' if git_state == GitState.STAGED else
                           'unstaged with changes' if git_state == GitState.CHANGED else
                           'untracked by git')
                log.error(f'{path} is {message}')
                self.__uncommitted += 1

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

        # Authoring implies to clean output directory, report deprecated markup, and don't tile background
        if options.get('authoring', False):
            options['showDeprecated'] = True

        # Save options to add to map's metadata
        self.__options = options

        # Save options into global ``settings`` dict
        settings.update(options)

        # Check we have been given a map source and get our manifest
        if 'source' in options:
            self.__manifest = Manifest(options['source'], single_file=options.get('singleFile'), id=options.get('id'))
        else:
            raise ValueError('No source manifest specified')
        self.__id = self.__manifest.id
        if self.__id is None:
            raise ValueError('No id given for map')
        self.__uuid = self.__manifest.uuid

        # Save for metadata
        git_status = self.__manifest.git_status
        self.__git_status = {'git-status': git_status} if git_status is not None else {}

        # All set to go
        log('Making map: {}'.format(self.__id))

        # Make sure our output directories exist
        map_base = options.get('output')
        if not os.path.exists(map_base):
            os.makedirs(map_base)
        self.__map_dir = os.path.join(map_base, self.__uuid)
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

        # Our source of knowledge, updated with information
        # about maps we've made, held in a global place
        sckan_version = self.__manifest.sckan_version
        knowledge_store = KnowledgeStore(map_base,
                                         clean_connectivity=settings.get('cleanConnectivity', False),
                                         sckan_version=sckan_version)
        settings['KNOWLEDGE_STORE'] = knowledge_store

        # Exclude shapes from a layer if they are in the base layer (FC maps)
        self.__shape_filters = None

        # For annotating functional connectivity diagrams
        self.__FC_annotator = None

        # The map we are making
        self.__flatmap = FlatMap(self.__manifest, self)

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
        self.__process_sources()

        # Finish flatmap processing (path routing, etc)
        self.__flatmap.close()

        # Do have any map layers?
        if len(self.__flatmap) == 0:
            raise ValueError('No map layers in sources...')

        # Save functional connectivity annotation
        if self.__FC_annotator is not None:
            self.__FC_annotator.save()

        # Output all features (as GeoJSON)
        self.__output_geojson()
        # Generate vector tiles from GeoJSON
        self.__make_vector_tiles()
        # Generate image tiles as needed
        self.__check_raster_tiles()

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

        settings['functionalConnectivity'] = (self.__manifest.kind == 'functional')
        if settings['functionalConnectivity']:
            self.__shape_filters = FCShapeFilters()
            if self.__manifest.annotation is not None:
                self.__FC_annotator = create_fc_annotator(self.__manifest.annotation)
            else:
                self.__FC_annotator = None
        for layer_number, source in enumerate(sorted(self.__manifest.sources, key=kind_order)):
            id = source.get('id')
            kind = source.get('kind')
            href = source['href']
            if settings['functionalConnectivity']:
                if kind in ['base', 'layer']:
                    source_layer = FCPowerpointSource(self.__flatmap, id, href, kind,
                                        source_range=get_range(source.get('slides')),
                                        shape_filters=self.__shape_filters,
                                        annotator=self.__FC_annotator,
                                        )
                else:
                    raise ValueError('Unsupported FC kind: {}'.format(kind))
            elif kind == 'slides':
                source_layer = PowerpointSource(self.__flatmap, id, href,
                                    source_range=get_range(source.get('slides')))
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
                    log.warning(msg)
            self.__flatmap.add_source_layers(layer_number, source_layer)

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

        # Save flatmap's metadata, including settings used to generate map
        metadata = self.__flatmap.metadata
        metadata['settings'] = self.__options
        metadata.update(self.__git_status)
        tile_db.add_metadata(metadata=json.dumps(metadata))

        # Save layer details in metadata
        tile_db.add_metadata(layers=json.dumps(self.__flatmap.layer_metadata()))
        # Save pathway details in metadata
        tile_db.add_metadata(pathways=json.dumps(self.__flatmap.connectivity()))
        # Save annotations in metadata
        tile_db.add_metadata(annotations=json.dumps(self.__flatmap.annotations))

        # Commit updates to the database
        tile_db.execute("COMMIT")

        # Update our knowledge base
        settings['KNOWLEDGE_STORE'].add_flatmap(self.__flatmap)

#*        ## TODO: set ``layer.properties`` for annotations...
#*        ##update_RDF(options['map_base'], options['map_id'], source, annotations)

        map_index = {
            'id': self.__id,
            'uuid': self.__uuid,
            'source': self.__manifest.url,
            'min-zoom': self.__zoom[0],
            'max-zoom': self.__zoom[1],
            'bounds': self.__flatmap.extent,
            'version': FLATMAP_VERSION,
            'image-layers': len(self.__raster_layers) > 0
        }
        if self.__flatmap.models is not None:
            map_index['taxon'] = self.__flatmap.models
        if self.__manifest.biological_sex is not None:
            map_index['biologicalSex'] = self.__manifest.biological_sex
        if settings.get('authoring', False):
            map_index['style'] = 'authoring'
        elif settings.get('functionalConnectivity', False):
            map_index['style'] = 'fcdiagram'
        else:
            map_index['style'] = 'flatmap'
        map_index.update(self.__git_status)

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
