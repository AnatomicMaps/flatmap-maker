#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2023 David Brooks
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

from io import BytesIO
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED
import os
import json
import logging
import requests
import openpyxl
import mimetypes
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dataclasses import dataclass
import shutil
from pathlib import Path

#===============================================================================

from mapmaker.flatmap import FlatMap, Manifest

#===============================================================================

MAPPING_URL = "mapmaker/output/data_mapping.json"

#===============================================================================

from mapmaker.utils import pathlib_path

#===============================================================================

class VersionMapping:
    def __init__(self):
        with open(MAPPING_URL, 'r') as f:
            self.__mappings = json.load(f)

    @property
    def available_versions(self):
        return [v['version'] for v in self.__mappings]

    def get_mapping(self, other_params):
        """
        : other_params: is a dictionary containing other data such as uuid and version
        """
        version = other_params.get('version', None)
        mapping = None
        if version == None:
            mapping = self.__mappings[0]
        else:
            for v in self.__mappings:
                if v['version'] == version:
                    mapping = v
        if mapping == None:
            raise Exception('Dataset-Description version-{} is not available'.format(version))
        for m in mapping['mapping']:
            if len(m[1])> 0:
                param = m[1][-1]
                if param in other_params:
                    m[2] = other_params[param]
        return mapping

#===============================================================================

class DatasetDescription:
    def __init__(self, description_file, flatmap, version):
        """
        : description_file: is a pat to description.json
        : flatmap: is a Flatmap instance
        : version: is SDS version
        """
        
        other_params = {'version':version}
        other_params['id'] = ['URL', 'UUID']
        other_params['id_type'] = [flatmap.metadata.get('source'), flatmap.uuid]

        self.__mapping = VersionMapping().get_mapping(other_params)
        self.__workbook = self.__load_template_workbook(self.__mapping['template_url'])
        
        try:
            if description_file.startswith('file'):
                description_file = pathlib_path(description_file)
            with open(description_file, 'r') as fd:
                self.__description = json.load(fd)
        except:
            logging.warning('Cannot create dataset: Cannot open path: {}'.format(description_file))
        
        for m in self.__mapping['mapping']:
             self.__write_cell(m)
        
    def __load_template_workbook(self, template_link):
        """
        : template_link: link to dataset_description.xlsx
        """
        headers = {'Content-Type': 'application/xlsx'}
        template = requests.request('GET', template_link, headers=headers)
        workbook = openpyxl.load_workbook(BytesIO(template.content))
        return workbook
        
    def __write_cell(self, map):
        worksheet = self.__workbook.worksheets[0]
        data_pos = self.__mapping.get('data_pos', 3)
        key, dsc, default = map
        values = default if isinstance(default, list) else [default]

        if len(dsc) == 1:
            if dsc[0] in self.__description:
                values = self.__description[dsc[-1]] if isinstance(self.__description[dsc[-1]], list) else [self.__description[dsc[-1]]]
        elif len(dsc) > 1:
            tmp_values = self.__description
            for d in dsc:
                if isinstance(tmp_values, dict):
                    tmp_values = tmp_values.get(d, {})
                elif isinstance(tmp_values, list):
                    tmp_values = [val.get(d, '') for val in tmp_values]
            
            if len(tmp_values) > 0:
                values = tmp_values if isinstance(tmp_values, list) else [tmp_values]

        for row in worksheet.rows:
            if row[0].value == None:
                break
            if row[0].value.lower().strip() == key:
                for pos in range(len(values)):
                    row[pos+data_pos].value = str(values[pos])

    def get_byte(self):
        buffer = BytesIO()
        self.__workbook.save(buffer)
        buffer.seek(0)
        return buffer
    
    def get_json(self):
        return self.__description
    
    def close(self):
        self.__workbook.close()
    
#===============================================================================

@dataclass
class DatasetFile:
    filename: str
    fullpath: Path
    timestamp: datetime
    description: str
    file_type: str

#===============================================================================

class DirectoryManifest:
    COLUMNS = (
        'filename',
        'timestamp',
        'description',
        'file type',
    )

    def __init__(self, manifest, is_git=True, metadata_columns=None):
        self.__manifest = manifest
        self.__metadata_columns = metadata_columns if metadata_columns is not None else []
        self.__files = []
        self.__file_records = []
        self.__repo_datetime = None
        if is_git:
            commit = self.__manifest.git_repository._MapRepository__repo.head.commit
            tzinfo = timezone(timedelta(seconds=commit.author_tz_offset))
            commit_time = datetime.fromtimestamp(float(commit.committed_date), tzinfo)
            self.__repo_datetime =  commit_time
        
    def __get_repo_datetime(self, fullpath=None):
        if self.__repo_datetime != None:
            return self.__repo_datetime
        else:
            return datetime.fromtimestamp(os.path.getmtime(fullpath))

    @property
    def files(self):
        return self.__files
    
    @property
    def file_list(self):
        return [f.fullpath for f in self.__files]

    def add_file(self, filename, description, **metadata):
        fullpath = (self.__manifest._Manifest__url / filename).resolve()
        file_type = mimetypes.guess_type(filename, strict=False)[0]
        file_type = fullpath.suffix if file_type == None else file_type
        dataset_file = DatasetFile(fullpath.name,
                                   fullpath,
                                   self.__get_repo_datetime(fullpath),
                                   description,
                                   file_type)
        self.__files.append(dataset_file)
        record = [
            dataset_file.filename,
            dataset_file.timestamp.isoformat(),
            dataset_file.description,
            dataset_file.file_type
        ]
        for column_name in self.__metadata_columns:
            record.append(metadata.get(column_name))
        self.__file_records.append(record)

    def get_byte(self):
        workbook = openpyxl.Workbook()
        worksheet = workbook.active
        for col, value in enumerate(self.COLUMNS + tuple(self.__metadata_columns), start=1):
            worksheet.cell(row=1, column=col, value=value)
        for row, record in enumerate(self.__file_records, start=2):
            for col, value in enumerate(record, start=1):
                worksheet.cell(row=row, column=col, value=value)
        buffer = BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        workbook.close()
        return buffer

#===============================================================================

class FlatmapSource:
    def __init__(self, manifest, flatmap, is_git=True):
        """
        : manifest: a Manifest instance
        : flatmap: a Flatmap instance
        : is_git: a binary whether the source manage by repo or not
        """
        
        # creating dataset manifest.xlsx
        species = manifest.models
        metadata = {'species': species} if species is not None else {}
        
        directory_manifest = DirectoryManifest(manifest, is_git, list(metadata.keys()))
        
        if is_git:
            # adding files to be store in primary directory    
            directory_manifest.add_file(pathlib_path(manifest.description), 'flatmap description', **metadata)
            if manifest.anatomical_map != None:
                directory_manifest.add_file(pathlib_path(manifest.anatomical_map), 'flatmap annatomical map', **metadata)
            if manifest.properties != None:
                directory_manifest.add_file(pathlib_path(manifest.properties), 'flatmap properties', **metadata)
            if manifest.connectivity_terms != None:
                directory_manifest.add_file(pathlib_path(manifest.connectivity_terms), 'flatmap connectivity terms', **metadata)
            for connectivity_file in manifest.connectivity:
                directory_manifest.add_file(pathlib_path(connectivity_file), 'flatmap connectivity', **metadata)
            for source in manifest.sources:
                if source['href'].split(':', 1)[0] in ['file']:
                    directory_manifest.add_file(pathlib_path(source['href']), 'flatmap source', **metadata)
            manifest_dir = pathlib_path(manifest.description).parent
            manifest_path = (manifest_dir / pathlib_path(manifest.url).name).resolve()
            directory_manifest.add_file(manifest_path, 'manifest to built map', **metadata)
            # adding other file
            for file in os.listdir(manifest_dir):
                file_path = (manifest_dir / file).resolve()
                if file_path not in directory_manifest.file_list and file_path.is_file():
                    directory_manifest.add_file(file_path, 'another primary flatmap file', **metadata)
        else:
            for file in os.listdir(flatmap.map_dir):
                file_path = (Path(flatmap.map_dir) / file).resolve()
                if file_path.is_file():
                    directory_manifest.add_file(file_path, 'derivative file to be used by map server', **metadata)

        self.__directory_manifests = [directory_manifest]

    @property
    def directory_manifests(self):
        return self.__directory_manifests

    @property
    def dataset_image(self):
        for directory_manifest in self.__directory_manifests:
            for file in directory_manifest.files:
                if file.filename.endswith('.svg'):
                    return file.fullpath
        return None
    
    def copy_to_archive(self, archive, target):
        for directory_manifest in self.directory_manifests:
            for file in directory_manifest.files:
                zinfo = ZipInfo.from_file(str(file.fullpath), arcname=f'{target}/{file.filename}')
                zinfo.compress_type = ZIP_DEFLATED
                timestamp = file.timestamp
                zinfo.date_time = (timestamp.year, timestamp.month, timestamp.day,
                                timestamp.hour, timestamp.minute, timestamp.second)
                with open(file.fullpath, "rb") as src, archive.open(zinfo, 'w') as dest:
                    shutil.copyfileobj(src, dest, 1024*8)
            manifest_workbook = directory_manifest.get_byte()
            archive.writestr(f'{target}/manifest.xlsx', manifest_workbook.getvalue())
            manifest_workbook.close()

#===============================================================================

class SparcDataset:
    def __init__(self, manifest: Manifest, flatmap: FlatMap):
        self.__manifest = manifest
        self.__flatmap = flatmap
        
    def generate(self):
        # generate dataset_description
        self.__description = DatasetDescription(self.__manifest.description, self.__flatmap, version=None)

        # generate primary source
        self.__primary = FlatmapSource(self.__manifest, self.__flatmap)

        # generate derivative source
        self.__derivative = FlatmapSource(self.__manifest, self.__flatmap, is_git=False)

    def save(self, dataset: str):
        # create archive
        dataset_archive = ZipFile(dataset, mode='w', compression=ZIP_DEFLATED)

        # adding dataset_description
        desc_byte = self.__description.get_byte()
        dataset_archive.writestr('files/dataset_description.xlsx', desc_byte.getvalue())
        desc_byte.close()
        self.__description.close()
        
        # copy primary data
        self.__primary.copy_to_archive(dataset_archive, 'files/primary')

        # this one save derivatives
        self.__derivative.copy_to_archive(dataset_archive, 'files/derivative')

        # create and save proper readme file, generated for dataset_description
        self.__add_readme(dataset_archive)

        # save banner
        if len(self.__manifest.sources) > 0:
            banner_file = self.__manifest.sources[0].get('href')
            dataset_archive.write(pathlib_path(banner_file), 'files/banner.svg')

        # close archive
        dataset_archive.close()

    def __add_readme(self, archive):
        # load flatmap description
        readme = ['# FLATMAP DESCRIPTION'] + self.__metadata_parser(self.__description.get_json())
        # load flatmat setup
        readme += ['# FLATMAP SETTINGS'] + self.__metadata_parser(self.__flatmap.metadata)        
        archive.writestr(f'files/readme.md', '\n'.join(readme))

    def __metadata_parser(self, data):
        metadata = []
        for key, val in data.items():
                metadata += [f'## {key.capitalize()}']
                if isinstance(val, dict):
                    for subkey, subval in val.items():
                        metadata += [f'- {subkey}: {subval}']
                elif isinstance(val, list):
                    for subval in val:
                        if isinstance(subval, dict):
                            for subsubkey, subsubval in subval.items():
                                metadata += [f'- {subsubkey}: {subsubval}']
                            metadata += ['\n', '<br/>', '\n']
                        else:
                            metadata += [f'- {subval}']
                else:
                    metadata += [str(val), '\n']
        return metadata
        
#===============================================================================
