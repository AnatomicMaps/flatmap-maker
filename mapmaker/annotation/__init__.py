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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

#===============================================================================

from mapmaker.utils import log, relative_path

#===============================================================================

def term_normalise(term: str) -> str:
    name = term.split('/')[-1]
    if name.startswith('ilx_'):
        return f'ILX:{name[4:]}'
    elif name.startswith('UBERON_'):
        return f'ILX:{name[7:]}'
    else:
        return term

#===============================================================================

# create virtual table fts_labels if not exists fts using fts5(entity, label);
# insert into fts_labels (entity, label)  select entity, label from labels;

# select bm25(fts_labels), entity, label from fts_labels where label match ? order by bm25(fts), entity desc

@dataclass(kw_only=True)  # Requires Python 3.10
class Annotation:
    identifier: str = field(default_factory=str)
    name: str = field(default_factory=str)
    term: str = field(default_factory=str)
    sources: set[str] = field(default_factory=set)
    properties: dict[str, Any] = field(default_factory=dict)

    def as_dict(self):
        result = {}
        if self.identifier: result['id'] = self.identifier
        if self.name: result['name'] = self.name
        if self.term: result['term'] = self.term
        if self.sources: result['sources'] = sorted(self.sources)
        if len(self.properties): result['properties'] = self.properties
        return result

## parent ??

#===============================================================================

class Annotator:
    def __init__(self, annotation_file: str):
        if not relative_path(annotation_file):
            if annotation_file.startswith('file:'):
                annotation_file = annotation_file[5:]
            else:
                log.warning(f'Remote FC annotation at {annotation_file} will not be updated')
        self.__annotation_file = Path(annotation_file)
        self.__nerves_by_name: dict[str, Annotation] = {}                                 #! Nerve name -> Annotation
        self.__systems_by_name: dict[str, Annotation] = {}                                #! System name -> Annotation
        self.__organs_with_systems_by_name: dict[str, tuple[Annotation, set[str]]] = {}   #! Organ name -> (Annotation, Systems)
        self.__ftus_by_name_organ: dict[tuple[str, str], Annotation] = {}                 #! (Organ, FTU name) -> Annotation
        self.__annotations_by_id: dict[str, Annotation] = {}
        self.__connectivity: list = []  ## networkx.Graph()   ???
        self.__anatomy_lookup = AnatomyLookup()
        self.load()

    @property
    def annotation_file(self):
        return self.__annotation_file

    @property
    def ftu_names_with_organ(self):
        return self.__ftus_by_name_organ.keys()

    @property
    def organ_names(self):
        return self.__organs_with_systems_by_name.keys()

    @property
    def nerve_names(self):
        return self.__nerves_by_name.keys()

    @property
    def system_names(self):
        return self.__systems_by_name.keys()

    def get_ftu_with_organ(self, name, organ_name):
    #==============================================
        return self.__ftus_by_name_organ[(name, organ_name)]

    def get_nerve_by_name(self, name):
    #=================================
        return self.__nerves_by_name.get(name)

    def get_system_by_name(self, name):
    #==================================
        return self.__systems_by_name.get(name)

    def get_organ_with_systems(self, name):
    #======================================
        return self.__organs_with_systems_by_name.get(name)

    def find_annotation(self, identifier: str) -> Optional[Annotation]:
    #==================================================================
        return self.__annotations_by_id.get(identifier)

    def find_term_by_names(self, *names) -> Optional[str]:
    #=====================================================
        pass

    def find_ftu_by_names(self, organ_name: str, ftu_name: str) -> Optional[Annotation]:
    #======================================================================================
        return self.__ftus_by_name_organ.get((organ_name, ftu_name))

    def get_ftu_annotation(self, organ_name: str, ftu_name: str, source: str) -> Annotation:
    #=======================================================================================
        if (annotation := self.find_ftu_by_names(organ_name, ftu_name)) is None:
            annotation = Annotation(name=ftu_name)
            self.__add_annotation(annotation)
            self.__ftus_by_name_organ[(organ_name, ftu_name)] = annotation
        annotation.sources.add(source)
        return annotation

    def get_organ_annotation(self, name: str, source: str, system_names: Iterable[str]):
    #===================================================================================
        if (organ_system := self.__organs_with_systems_by_name.get(name)) is not None:
            annotation = organ_system[0]
            organ_system[1].update(system_names)
        else:
            annotation = Annotation(name=name)
            self.__add_annotation(annotation)
            self.__organs_with_systems_by_name[name] = (annotation, set(system_names))
        annotation.sources.add(source)
        return annotation

    def get_nerve_annotation(self, name: str, source: str):
    #======================================================
        if (annotation := self.__nerves_by_name.get(name)) is None:
            annotation = Annotation(name=name)
            self.__add_annotation(annotation)
            self.__nerves_by_name[name] = annotation
        self.__nerves_by_name[name].sources.add(source)
        return annotation

    def get_system_annotation(self, name: str, source: str):
    #=======================================================
        if (annotation := self.__systems_by_name.get(name)) is None:
            annotation = Annotation(name=name)
            self.__add_annotation(annotation)
            self.__systems_by_name[name] = annotation
        self.__systems_by_name[name].sources.add(source)
        return annotation

    def __add_annotation(self, annotation: Annotation):
    #==================================================
        if annotation.identifier != '':
            if annotation.identifier in self.__annotations_by_id:
                log.error(f'Duplicate identifier in FC annotation: {annotation.identifier}')
            else:
                self.__annotations_by_id[annotation.identifier] = annotation

    # The following three methods are used by the sub-classed loaders
    def add_ftu_with_organ_annotation(self, annotation: Annotation, organ: str):
    #===========================================================================
        if (key := (organ, annotation.name)) not in self.__ftus_by_name_organ:
            self.__ftus_by_name_organ[key] = annotation
            self.__add_annotation(annotation)

    def add_organ_with_systems_annotation(self, annotation: Annotation, systems: set[str]):
    #======================================================================================
        if (name := annotation.name) not in self.__organs_with_systems_by_name:
            self.__organs_with_systems_by_name[name] = (annotation, systems)
            self.__add_annotation(annotation)

    def add_nerve_annotation(self, annotation: Annotation):
    #=======================================================
        if (name := annotation.name) not in self.__nerves_by_name:
            self.__nerves_by_name[name] = annotation
            self.__add_annotation(annotation)

    def add_system_annotation(self, annotation: Annotation):
    #=======================================================
        if (name := annotation.name) not in self.__systems_by_name:
            self.__systems_by_name[name] = annotation
            self.__add_annotation(annotation)

    def load(self):
    #==============
        pass

    def save(self):
    #==============
        pass

#===============================================================================

from .json_annotator import JsonAnnotator
from .xlsx_annotator import XlsxAnnotator
from .xlsx_annotator_v2 import XlsxAnnotatorV2

#===============================================================================

def create_annotator(annotation_file: str) -> Annotator:
#=======================================================
    if annotation_file.endswith('.json'):
        return JsonAnnotator(annotation_file)
    elif annotation_file.endswith('.xlsx'):
        if '-v2' in annotation_file:
            return XlsxAnnotatorV2(annotation_file)
        else:
            return XlsxAnnotator(annotation_file)
    else:
        raise TypeError('Unsupported annotation file format: {annotation_file}')

#===============================================================================
