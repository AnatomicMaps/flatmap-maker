#===============================================================================
#
#  Flatmap tools
#
#  Copyright (c) 2023 David Brooks
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

import argparse
import json
import logging
import pathlib
import shutil
import sqlite3
import tempfile

#===============================================================================

import git
import giturlparse

#===============================================================================

from flatmapknowledge import KnowledgeStore

from mapmaker.maker import Manifest

#===============================================================================

__version__ = '1.0.0'

#===============================================================================

def normalise_identifier(id):
    return ':'.join([(s[:-1].lstrip('0') + s[-1])
                        for s in id.split(':')])

#===============================================================================

class MetadataDatabase:
    def __init__(self, database):
        self.__db = sqlite3.connect(database)

    def add_metadata(self, **metadata):
        for name, value in metadata.items():
            value = json.dumps(value) if name == 'metadata' else value
            self.__db.execute('replace into metadata(name, value) values (?, ?);',
                                                                    (name, value))
    def close(self):
        self.__db.close()

    def commit(self):
        return self.__db.commit()

    def execute(self, sql):
        return self.__db.execute(sql)

    def metadata(self, name=None):
        if name is not None:
            result = self.__db.execute('select value from metadata where name=?;', (name, )).fetchone()[0]
            return json.loads(result) if name == 'metadata' else result
        else:
            return dict(self.__db.execute('select name, value from metadata;').fetchall())

#===============================================================================

class FlatmapError(Exception):
    pass

#===============================================================================

class Flatmap:
    def __init__(self, flatmap_path):
        index_file = flatmap_path / 'index.json'
        mbtiles = flatmap_path / 'index.mbtiles'
        if not flatmap_path.is_dir() or not index_file.exists() or not mbtiles.exists():
            raise FlatmapError('Invalid or missing directory')

        with open(index_file) as fp:
            self.__index = json.loads(fp.read())
        version = self.__index.get('version', 1.0)
        if version < 1.3:
            raise FlatmapError('Version is too old')

        db = MetadataDatabase(mbtiles)
        metadata = db.metadata(name='metadata')
        db.close()

        if (('id' not in metadata or flatmap_path.name != metadata['id'])
         and ('uuid' not in metadata or flatmap_path.name != metadata['uuid'].split(':')[-1])):
            raise FlatmapError('Id mismatch')

        flatmap = {
            'id': metadata['id'],
            'source': metadata['source'],
            'version': version
        }
        if 'created' in metadata:
            flatmap['created'] = metadata['created']
        if 'taxon' in metadata:
            flatmap['taxon'] = normalise_identifier(metadata['taxon'])
            flatmap['describes'] = metadata['describes'] if 'describes' in metadata else flatmap['taxon']
        elif 'describes' in metadata:
            flatmap['taxon'] = normalise_identifier(metadata['describes'])
            flatmap['describes'] = flatmap['taxon']
        if 'biological-sex' in metadata:
            flatmap['biologicalSex'] = metadata['biological-sex']
        if 'uuid' in metadata:
            flatmap['uuid'] = metadata['uuid']
        if 'name' in metadata:
            flatmap['name'] = metadata['name']
        self.__flatmap = flatmap

    def __getitem__(self, key):
        return self.__flatmap[key]

    def __setitem__(self, key, value):
        self.__flatmap[key] = value

    def __delitem__(self, key):
        del self.__flatmap[key]

    def __contains__(self, key):
        return key in self.__flatmap

    def __len__(self):
        return len(self.__flatmap)

    def __repr__(self):
        return repr(self.__flatmap)

    @property
    def index(self):
        return self.__index

    def as_dict(self):
        return self.__flatmap

    def get(self, key, default=None):
        return self.__flatmap.get(key, default)

#===============================================================================

def latest_flatmaps(flatmap_root):
#=================================
    flatmaps_by_dir = {}
    root_path = pathlib.Path(flatmap_root).absolute()
    if not root_path.exists():
        logging.error(f'Missing source directory: {root_path}')
        return None
    elif root_path.is_dir():
        for flatmap_path in root_path.iterdir():
            if flatmap_path.is_dir():
                try:
                    flatmaps_by_dir[str(flatmap_path)] = Flatmap(flatmap_path)
                except FlatmapError as e:
                    logging.warning(f'{flatmap_path}: {e}')
                    continue
    maps_by_taxon_sex = {}
    for flatmap_dir, flatmap in flatmaps_by_dir.items():
        if ((created := flatmap.get('created')) is not None
        and (taxon := flatmap.get('taxon', flatmap.get('describes'))) is not None):
            map_key = (taxon, flatmap.get('biologicalSex', ''))
            if (map_key not in maps_by_taxon_sex
             or created > maps_by_taxon_sex[map_key][0]):
                maps_by_taxon_sex[map_key] = (created, flatmap_dir, flatmap)

    return { flatmap_dir: flatmap for _, flatmap_dir, flatmap in maps_by_taxon_sex.values() }

#===============================================================================

class FlatmapSource:
    def __init__(self, flatmap):
        map_source = flatmap['source']
        git_url = giturlparse.parse(map_source)
        if not git_url.valid:
            raise FlatmapError('Sources are not in a remote git repository')
        if not git_url.domain.endswith('physiomeproject.org'):
            raise FlatmapError('Only `physiomeproject.org` sources are currently supported')
        parts = git_url.groups_path.split('/')
        repo_path = f'{git_url.protocol}://{git_url.host}{git_url.port}/{git_url.owner}/{parts[0]}'
        working_dir = tempfile.TemporaryDirectory().name
        try:
            repo = git.Repo.clone_from(repo_path, working_dir)
        except git.exc.GitCommandError as e:
            raise FlatmapError(str(e))

        repo.head.reference = repo.commit(parts[-1])
        repo.head.reset(index=True, working_tree=True)
        self.__manifest = Manifest(f'{working_dir}/{git_url.repo}')

    @property
    def manifest(self):
        return self.__manifest

#===============================================================================

class FlatmapConvertor:
    def __init__(self, output_path, final_root=None):
        self.__output_path = output_path
        self.__final_root = final_root if final_root is not None else str(self.__output_path)
        self.__store = KnowledgeStore(output_path, create=False)

    def convert(self, flatmap_dir, manifest):
        output_dir = self.__output_path / manifest.uuid
        if output_dir.exists():
            return None
        shutil.copytree(flatmap_dir, output_dir)

        with open(output_dir / 'index.json') as fp:
            index = json.loads(fp.read())
        index['id'] = manifest.id
        index['uuid'] = manifest.uuid
        index['taxon'] = manifest.models
        index['describes'] = self.__store.entity_knowledge(manifest.models)['label']
        if 'image_layer' in index:
            index['image-layers'] = index.pop('image_layer')
        index['git-status'] = manifest.git_status
        index['style'] = 'flatmap'
        with open(output_dir / 'index.json', 'w') as fp:
            fp.write(json.dumps(index))

        mbtiles_file = output_dir / 'index.mbtiles'
        db = MetadataDatabase(mbtiles_file)
        metadata = db.metadata(name='metadata')

        metadata.pop('name', None)
        metadata['id'] = index['id']
        metadata['uuid'] = index['uuid']
        metadata['taxon'] = index['taxon']
        metadata['describes'] = index['describes']
        metadata['git-status'] = index['git-status']
        if 'biologicalSex' in index:
            metadata['biologicalSex'] = index['biologicalSex']

        db.execute('begin')
        db.execute("delete from metadata where name='id'")
        db.execute("delete from metadata where name='describes'")
        db.add_metadata(metadata=metadata)
        final_db_name = str(self.__final_root / manifest.uuid / 'index.mbtiles')
        db.add_metadata(name=final_db_name)
        db.add_metadata(description=final_db_name)
        db.commit()
        db.close()

        if self.__store.db is not None:
            self.__store.db.execute('begin')
            self.__store.db.execute('replace into flatmaps(id, models, created) values (?, ?, ?)',
                                        (manifest.uuid, manifest.models, metadata['created']))
            self.__store.db.commit()

        return metadata['uuid']

#===============================================================================

def main():
    parser = argparse.ArgumentParser(description='Upgrade most recent maps for each species to use GUIDs.')
    parser.add_argument('-v', '--version', action='version', version=__version__)
    parser.add_argument('--id', metavar='ID',
        help='Only process this map (and only if it is the latest for a species)')
    parser.add_argument('--list-only', action='store_true',
        help='List most recent maps without upgrading them')
    parser.add_argument('--verbose', action='store_true', help='Show progress')
    parser.add_argument('--dest', dest='dest_flatmaps', metavar='DESTINATION',
        help='Flatmap root to save maps into. Required if not `list-latest`')
    parser.add_argument('--final', dest='final_dest', metavar='FINAL_DESTINATION',
        help='Full path to flatmap root where destination maps will be placed. Optional, defaults to DESTINATION')
    parser.add_argument('--source', dest='source_flatmaps', required=True, metavar='SOURCE',
        help='Flatmap root to source maps. Required')
    args = parser.parse_args()

    logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s')
    if args.verbose:
        logging.getLogger().setLevel(logging.INFO)
    else:
        logging.getLogger().setLevel(logging.WARNING)

    if not args.list_only:
        if args.dest_flatmaps is None:
            parser.error('Destination root directory is required if not listing latest maps')
        elif args.dest_flatmaps == args.source_flatmaps:
            parser.error('Source and destination root directories must be different')
        if args.final_dest is not None and not args.final_dest.startswith('/'):
            parser.error('Final destination path must start with `/`')

    latest_maps = latest_flatmaps(args.source_flatmaps)
    if latest_maps is None:
        exit()
    output_dict = {}
    if args.list_only:
        for flatmap_dir, flatmap in latest_maps.items():
            taxon = flatmap['taxon']
            if 'uuid' in flatmap:
                logging.warning(f'{taxon} already has GUID in source {flatmap_dir} -- skipped processing')
                continue
            elif args.id is not None and args.id != flatmap['id']:
                continue
            logging.info(f'Processing {taxon} from {flatmap_dir}')
            output_dict[flatmap_dir] = flatmap.as_dict()

    else:
        output_path = pathlib.Path(args.dest_flatmaps).absolute()
        if not output_path.exists():
            logging.error(f'Missing destination directory: {output_path}')
            exit()
        convertor = FlatmapConvertor(output_path, args.final_dest)
        for flatmap_dir, flatmap in latest_maps.items():
            taxon = flatmap['taxon']
            if 'uuid' in flatmap:
                logging.warning(f'{taxon} already has GUID in source {flatmap_dir} -- skipped processing')
                continue
            elif args.id is not None and args.id != flatmap['id']:
                continue
            logging.info(f'Processing {taxon} from source {flatmap_dir}')
            try:
                flatmap_source = FlatmapSource(flatmap)
            except FlatmapError as e:
                logging.warning(f'{flatmap_dir}: {e}')
                continue
            guid = convertor.convert(flatmap_dir, flatmap_source.manifest)
            if guid is not None:
                output_dict[taxon] = guid
                logging.info(f'Saved {taxon} as {guid} in destination')
            else:
                logging.warning(f'{taxon} with GUID already exists in destination -- not overwritten')

    print(json.dumps(output_dict, indent=4))

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================
