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
from copy import deepcopy
from datetime import datetime
from enum import Enum
import multiprocessing
import os
import pathlib
import shutil
import tempfile
from typing import Optional
from urllib.parse import urljoin

#===============================================================================

import git
import giturlparse

#===============================================================================

# A clone from GitHub can wait asking for password input, esp. if we try to clone
# an unknown repository. Hence we run the clone in a separate process and abort after
# GIT_CLONE_TIMEOUT seconds.

GIT_CLONE_TIMEOUT = 300     # 5 minutes

def __clone_repo(repo_path: str, working_directory: str, output_queue: multiprocessing.Queue):
    repo = git.Repo.clone_from(repo_path, working_directory)
    output_queue.put(repo)

def clone_from_with_timeout(repo_path: str, working_directory: str) -> git.Repo:
    repo_queue: multiprocessing.Queue[git.Repo] = multiprocessing.Queue()
    clone_process = multiprocessing.Process(target=__clone_repo, args=(repo_path, working_directory, repo_queue))
    clone_process.start()
    if clone_process.join(GIT_CLONE_TIMEOUT) is None:
        if clone_process.exitcode is None:
            clone_process.kill()    # still running so kill clone
            raise TimeoutError(f'Git clone of {repo_path} timed out, aborting')
    return repo_queue.get()

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
    def __init__(self, working_dir: pathlib.Path, repo: Optional[git.Repo]=None):
        try:
            if repo is None:
                self.__repo = git.Repo(working_dir, search_parent_directories=True) # type:ignore
            else:
                self.__repo = repo
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
    def description(self) -> Optional[str]:
        try:
            return self.__repo.git.describe()
        except git.GitCommandError:
            pass

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

class SourceManifest:
    def __init__(self, description: dict, manifest: 'Manifest'):
        self.__id = description['id']
        href = manifest.check_and_normalise_path(description['href'], 'Flatmap source file')
        if href is None:
            raise ValueError('Source in manifest has no `href`')
        self.__href = href
        self.__kind = description.get('kind', '')
        self.__boundary = description.get('boundary')
        self.__feature = description.get('feature')
        self.__source_range = (([int(n) for n in source_range] if isinstance(source_range, list)
                                                               else [int(source_range)])
                                    if (source_range := description.get('slides')) is not None
                                    else None)
        self.__zoom = description['zoom'] if self.__feature is not None else 0

    @property
    def boundary(self) -> Optional[str]:
        return self.__boundary

    @property
    def feature(self) -> Optional[str]:
        return self.__feature

    @property
    def href(self) -> str:
        return self.__href

    @property
    def id(self) -> str:
        return self.__id

    @property
    def kind(self) -> str:
        return self.__kind

    @property
    def source_range(self) -> Optional[list[int]]:
        return self.__source_range

    @property
    def zoom(self) -> int:
        return self.__zoom

#===============================================================================

class Manifest:
    def __init__(self, manifest_path, single_file=None, id=None, ignore_git=False, manifest:Optional[str]=None, commit=None):
        self.__temp_directory = None
        if single_file is not None:
            ignore_git = True
        if ignore_git:
            self.__repo = None
        elif ((manifest_path.startswith('http:') or manifest_path.startswith('https:'))
          and manifest is not None):
            # Create a temporary directory in which to clone the map's source
            self.__temp_directory = tempfile.mkdtemp()
            working_directory = self.__temp_directory
            # An unknown GitHub repo prompts for password and doesn't timeout so we
            # run the clone in it's own process with a timeout
            repo = clone_from_with_timeout(manifest_path, working_directory)
            if commit is not None:
                repo.git.checkout(commit)
            manifest_path = os.path.join(working_directory, manifest)   # type:ignore
            self.__repo = MapRepository(pathlib.Path(working_directory), repo)
        else:
            self.__repo = MapRepository(pathlib.Path(manifest_path).parent)
        self.__path = FilePath(manifest_path)
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
            self.__raw_manifest = deepcopy(self.__manifest)
            self.__sources = [SourceManifest(self.__manifest['sources'], self)]
        else:
            # Check the manifest itself is committed into the repository
            self.__check_committed(self.__url, 'Flatmap source manifest')

            self.__manifest = self.__path.get_json()
            self.__raw_manifest = deepcopy(self.__manifest)

            if id is not None:
                if ignore_git:
                    self.__manifest['id'] = id
                else:
                    raise ValueError('`--id` can only be used with `--authoring` and/or `--ignore-git`')
            elif 'id' not in self.__manifest:
                raise ValueError('No `id` specified in manifest')

            self.__neuron_connectivity = self.__manifest.get('neuronConnectivity', [])

            if 'sources' not in self.__manifest:
                raise ValueError('No sources given for manifest')
            self.__sources = [SourceManifest(source, self) for source in self.__manifest['sources']]

            if 'anatomicalMap' in self.__manifest:
                self.__manifest['anatomicalMap'] = self.check_and_normalise_path(self.__manifest['anatomicalMap'], 'Flatmap anatomical map')
            if 'annotation' in self.__manifest:
                self.__manifest['annotation'] = self.check_and_normalise_path(self.__manifest['annotation'], 'Flatmap annotation')
            if 'description' in self.__manifest:
                self.__manifest['description'] = self.check_and_normalise_path(self.__manifest['description'], 'Flatmap description')
            if 'connectivityTerms' in self.__manifest:
                self.__manifest['connectivityTerms'] = self.check_and_normalise_path(self.__manifest['connectivityTerms'], 'Flatmap connectivity terms')
            if 'properties' in self.__manifest:
                self.__manifest['properties'] = self.check_and_normalise_path(self.__manifest['properties'], 'Flatmap properties')
            if 'proxyFeatures' in self.__manifest:
                self.__manifest['proxyFeatures'] = self.check_and_normalise_path(self.__manifest['proxyFeatures'], 'Flatmap proxy features')
            for path in self.__manifest.get('connectivity', []):
                self.__connectivity.append(self.check_and_normalise_path(path, 'Flatmap connectivity'))
            if not ignore_git and self.__uncommitted:
                raise ValueError("Not all sources are commited into git -- was the '--authoring' or '--ignore-git' option intended?")

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
    def proxy_features(self):
        return self.__manifest.get('proxyFeatures')

    @property
    def file_set(self) -> list[ManifestFile]:
        return self.__clean_file_set

    @property
    def git_repository(self):
        return self.__repo

    @property
    def git_status(self) -> Optional[dict]:
        if self.__repo is not None and self.__repo.sha is not None:
            status = {
                'sha': self.__repo.sha,
                'remotes': self.__repo.remotes,
                'committed': self.__repo.committed
            }
            if (description := self.__repo.description) is not None:
                status['description'] = description
            return status

    @property
    def id(self):
        return self.__manifest['id']

    @property
    def kind(self):                 #! Either ``anatomical`` or ``functional``
        return self.__manifest.get('kind', 'anatomical')

    @property
    def raw_manifest(self):
        return self.__raw_manifest

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
        return self.__manifest.get('sckan-version')

    @property
    def sources(self) -> list[SourceManifest]:
        return self.__sources

    @property
    def url(self):
        if (self.__repo is not None
        and (blob_url := self.__repo.path_blob_url(self.__url)) is not None):
            return blob_url
        return self.__url

    def clean_up(self):
    #==================
        if self.__temp_directory is not None:
            shutil.rmtree(self.__temp_directory)

    def check_and_normalise_path(self, path: str, desc: str='') -> str|None:
    #=======================================================================
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
