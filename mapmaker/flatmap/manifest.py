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

from collections import namedtuple
from datetime import datetime
from enum import Enum
import os
import pathlib
from typing import Optional
from urllib.parse import urljoin

#===============================================================================

import git
import giturlparse

#===============================================================================

from mapmaker.utils import log, FilePath

#===============================================================================

GITHUB_GIT_HOST = 'github.com'
PHYSIOMEPROJECT_GIT_HOST = 'physiomeproject.org'

#===============================================================================

class GitState(Enum):
    UNKNOWN   = 0
    DONTCARE  = 1
    STAGED    = 2
    CHANGED   = 3
    UNTRACKED = 4

#===============================================================================

ManifestFile = namedtuple('ManifestFile', ['path', 'description'])

#===============================================================================

class MapRepository:
    def __init__(self, working_dir: pathlib.Path):
        try:
            self.__repo = git.Repo(working_dir, search_parent_directories=True)     # type:ignore
            self.__repo_path = pathlib.Path(self.__repo.working_dir).absolute()     # type:ignore
            self.__changed_items = [ item.a_path for item in self.__repo.index.diff(None) ]
            self.__staged_items = [ item.a_path for item in self.__repo.index.diff('HEAD') ]
            self.__untracked_files = self.__repo.untracked_files
            self.__upstream_base = self.__get_upstream_base()
        except git.InvalidGitRepositoryError:
            raise ValueError("Flatmap sources must be in a git managed directory ('--authoring' or '--ignore-git' option intended?)")

    @property
    def committed(self) -> datetime:
        return self.__repo.head.commit.committed_datetime

    @property
    def remotes(self) -> dict[str, str]:
        return {
            remote.name: giturlparse.parse(remote.url).url2https
                for remote in self.__repo.remotes
            }

    @property
    def sha(self) -> str:
        return self.__repo.head.commit.hexsha

    def __git_path(self, path):
        if self.__repo is not None:
            if path.startswith('file://'):
                path = path[7:]
            full_path = pathlib.Path(os.path.abspath(path))
            if full_path.is_relative_to(self.__repo_path):
                return str(full_path.relative_to(self.__repo_path))

    def __get_upstream_base(self) -> Optional[str]:
        url = None
        for remote in self.__repo.remotes:
            https_url = giturlparse.parse(remote.url).url2https
            url = giturlparse.parse(https_url)
            if (url.host.endswith(GITHUB_GIT_HOST)
             or url.host.endswith(PHYSIOMEPROJECT_GIT_HOST)):
                break
        if url is not None:
            raw_folder = ('blob/' if url.host.endswith(GITHUB_GIT_HOST) else
                          'rawfile/' if url.host.endswith(PHYSIOMEPROJECT_GIT_HOST) else
                          '')
            return f'{url.protocol}://{url.host}{url.port}/{url.owner}/{url.repo}/{raw_folder}{self.__repo.head.commit.hexsha}/'  # type: ignore

    def status(self, path: str) -> GitState:
    #=======================================
        if (git_path := self.__git_path(path)) is not None:
            if git_path in self.__untracked_files:
                return GitState.UNTRACKED
            try:
                _ = self.__repo.head.commit.tree.join(git_path)
            except KeyError:
                log.warning(f"{path} is missing from the manifest's directory")
                return GitState.UNKNOWN
            return (GitState.UNTRACKED if git_path in self.__untracked_files else
                    GitState.CHANGED if git_path in self.__changed_items else
                    GitState.STAGED if git_path in self.__staged_items else
                    GitState.DONTCARE)
        else:
            log.warning(f"{path} is not under git control in the manifest's directory")
        return GitState.UNKNOWN

    def path_blob_url(self, path):
    #=============================
        if (self.__upstream_base is not None
        and (git_path := self.__git_path(path)) is not None):
            return urljoin(self.__upstream_base, git_path)

#===============================================================================

class Manifest:
    def __init__(self, manifest_path, single_file=None, id=None, ignore_git=False):
        self.__path = FilePath(manifest_path)
        if single_file is not None:
            ignore_git = True
        if ignore_git:
            self.__repo = None
        else:
            self.__repo = MapRepository(pathlib.Path(manifest_path).parent)
        self.__ignore_git = ignore_git
        self.__url = self.__path.url
        self.__connections = {}
        self.__connectivity = []
        self.__neuron_connectivity = []
        self.__uncommitted = 0
        self.__clean_file_set: list[ManifestFile] = []

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
            self.__check_committed(self.__url, 'Flatmap source manifest')

            self.__manifest = self.__path.get_json()
            if id is not None:
                if ignore_git:
                    self.__manifest['id'] = id
                else:
                    raise ValueError('`--id` can only be used with `--authoring` and/or `--ignore-git`')
            elif 'id' not in self.__manifest:
                raise ValueError('No `id` specified in manifest')

            if self.__manifest.get('sckan-version', 'production') not in ['production', 'staging']:
                raise ValueError("'sckan-version' in manifest must be `production' or 'staging'")
            for model in self.__manifest.get('neuronConnectivity', []):
                self.__neuron_connectivity.append(model)

            if 'sources' not in self.__manifest:
                raise ValueError('No sources given for manifest')
            for source in self.__manifest['sources']:
                source['href'] = self.__check_and_normalise_path(source['href'], 'Flatmap source file')
            if 'anatomicalMap' in self.__manifest:
                self.__manifest['anatomicalMap'] = self.__check_and_normalise_path(self.__manifest['anatomicalMap'], 'Flatmap anatomical map')
            if 'annotation' in self.__manifest:
                self.__manifest['annotation'] = self.__check_and_normalise_path(self.__manifest['annotation'], 'Flatmap annotation')
            if 'description' in self.__manifest:
                self.__manifest['description'] = self.__check_and_normalise_path(self.__manifest['description'], 'Flatmap description')
            if 'connectivityTerms' in self.__manifest:
                self.__manifest['connectivityTerms'] = self.__check_and_normalise_path(self.__manifest['connectivityTerms'], 'Flatmap connectivity terms')
            if 'properties' in self.__manifest:
                self.__manifest['properties'] = self.__check_and_normalise_path(self.__manifest['properties'], 'Flatmap properties')
            for path in self.__manifest.get('connectivity', []):
                self.__connectivity.append(self.__check_and_normalise_path(path, 'Flatmap connectivity'))
            if not ignore_git and self.__uncommitted:
                raise TypeError("Not all sources are commited into git -- was the '--authoring' or '--ignore-git' option intended?")

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
    def description(self):
        return self.__manifest.get('description')

    @property
    def file_set(self) -> list[ManifestFile]:
        return self.__clean_file_set

    @property
    def git_repository(self):
        return self.__repo

    @property
    def git_status(self):
        if self.__repo is not None and self.__repo.sha is not None:
            return {
                'sha': self.__repo.sha,
                'remotes': self.__repo.remotes,
                'committed': self.__repo.committed
            }

    @property
    def id(self):
        return self.__manifest['id']

    @property
    def kind(self):
        return self.__manifest.get('kind', 'anatomical')

    @property
    def manifest(self):
        return self.__manifest

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
        if (self.__repo is not None
        and (blob_url := self.__repo.path_blob_url(self.__url)) is not None):
            return blob_url
        return self.__url

    def __check_and_normalise_path(self, path: str, desc: str='') -> str|None:
    #=========================================================================
        if path.strip() == '':
            return None
        normalised_path = self.__path.join_url(path)
        if not self.__ignore_git:
            self.__check_committed(normalised_path, desc)
        return normalised_path

    def __check_committed(self, path: str, desc: str=''):
    #====================================================
        if self.__repo is not None:
            git_state = self.__repo.status(path)
            if git_state == GitState.DONTCARE:
                self.__clean_file_set.append(ManifestFile(path, desc))
            else:
                message = ('unknown to git' if git_state == GitState.UNKNOWN else
                           'staged to be committed' if git_state == GitState.STAGED else
                           'unstaged with changes' if git_state == GitState.CHANGED else
                           'untracked by git')
                log.error(f'{path} is {message}')
                self.__uncommitted += 1

#===============================================================================
