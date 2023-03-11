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

from collections import defaultdict
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

#===============================================================================

from mapmaker.utils import relative_path

#===============================================================================

# create virtual table fts_labels if not exists fts using fts5(entity, label);
# insert into fts_labels (entity, label)  select entity, label from labels;

# select bm25(fts_labels), entity, label from fts_labels where label match ? order by bm25(fts), entity desc

@dataclass(kw_only=True)  # Requires Python 3.10
class Annotation:
    name: str = field(default_factory=str)
    term: str = field(default_factory=str)
    parents: str = field(default_factory=str)
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.term is None:
            self.term = ''
        if self.parents is None:
            self.parents = ''
        else:
            parents = sorted([p.strip() for p in self.parents.split(',')], key=str.lower)
            self.parents = ', '.join(parents)

    @property
    def parent_list(self):
        return sorted([p.strip() for p in self.parents.split(',')], key=str.lower)

    @parent_list.setter
    def parent_list(self, parents):
        self.parents = ', '.join(sorted(parents, key=str.lower))

#===============================================================================

class JsonAnnotations:
    def __init__(self, annotation_file: str):
        if not relative_path(annotation_file) and annotation_file.startswith('file:'):
            annotation_file = annotation_file[5:]
        self.__annotation_file = Path(annotation_file)

        self.__annotation_dict = defaultdict(list)
        self.__systems_by_name: dict[str, Annotation] = {}
        self.__nerves_by_name_parent: dict[tuple[str, str], Annotation] = {}
        self.__vessels_by_name: dict[str, Annotation] = {}
        self.__organs_by_name: dict[str, Annotation] = {}
        self.__ftus_by_name_organ: dict[tuple[str, str], Annotation] = {}
        self.__organ_records: dict[str, dict] = {}

        if self.__annotation_file.exists():
            with open(self.__annotation_file) as fp:
                self.__annotation_dict = json.load(fp)
                for system in self.__annotation_dict.get('Systems', []):
                    if (name := system.get('System Name', '')):
                        self.__systems_by_name[name] = Annotation(name=name, term=system.get('Models'))
                for nerve in self.__annotation_dict.get('Neural', []):
                    if (name := nerve.get('Nerve Name', '')):
                        parent = nerve.get('Organ/System')
                        self.__nerves_by_name_parent[(name, parent)] = Annotation(name=name, term=nerve.get('Models'),
                                                                                  parents=parent)
                for vessel in self.__annotation_dict.get('Vascular', []):
                    if (name := vessel.get('Vessel Name', '')):
                        self.__vessels_by_name[name] = Annotation(name=name, term=vessel.get('Models'))
                for organ in self.__annotation_dict.get('Organs', []):
                    if (name := organ.get('Organ Name', '')):
                        self.__organs_by_name[name] = Annotation(name=name, term=organ.get('Models'),
                                                                 parents=organ.get('Systems'))
                        self.__organ_records[name] = organ
                for ftu in self.__annotation_dict.get('FTUs', []):
                    if (name := ftu.get('FTU Name', '')):
                        organ = ftu.get('Organ')
                        self.__ftus_by_name_organ[(name, organ)] = Annotation(name=name, term=ftu.get('Model'),
                                                                              parents=organ)

    @property
    def systems(self) -> list[Annotation]:
        return list(self.__systems_by_name.values())

    @property
    def nerves(self) -> list[Annotation]:
        return list(self.__nerves_by_name_parent.values())

    @property
    def vessels(self) -> list[Annotation]:
        return list(self.__vessels_by_name.values())

    @property
    def organs(self) -> list[Annotation]:
        return list(self.__organs_by_name.values())

    @property
    def ftus(self) -> list[Annotation]:
        return list(self.__ftus_by_name_organ.values())

    def add_system(self, name: str):
    #===============================
        if name and name not in self.__systems_by_name:
            self.__systems_by_name[name] = Annotation(name=name)
            self.__annotation_dict['Systems'].append({
                'System Name': name,
                'Models': '',
                'Label': ''
            })

    def add_nerve(self, name: str, parent: str):
    #===========================================
        if name and (key := (name, parent)) not in self.__nerves_by_name_parent:
            self.__nerves_by_name_parent[key] = Annotation(name=name, parents=parent)
            self.__annotation_dict['Neural'].append({
                'Nerve Name': name,
                'Organ/System': parent,
                'Models': '',
                'Label': ''
            })

    def add_vessel(self, name: str):
    #=======================================================
        if name and name not in self.__vessels_by_name:
            self.__vessels_by_name[name] = Annotation(name=name)
            self.__annotation_dict['Vascular'].append({
                'Vessel Name': name,
                'Models': '',
                'Label': ''
            })

    def add_organ(self, name: str, systems: set[str]):
    #=================================================
        if name:
            if name in self.__organs_by_name:
                parents = set(self.__organs_by_name[name].parent_list)
                parents.update(systems)
                self.__organs_by_name[name].parent_list = parents
                self.__organ_records[name]['Systems'] = ', '.join(sorted(parents))
            else:
                parents = ', '.join(sorted(systems))
                self.__organs_by_name[name] = Annotation(name=name, parents=parents)
                organ = {
                    'Organ Name': name,
                    'Systems': parents,
                    'Models': '',
                    'Label': ''
                }
                self.__annotation_dict['Organs'].append(organ)
                self.__organ_records[name] = organ

    def add_ftu(self, name: str, organ: str, connected: bool=False):
    #===============================================================
        if name and (key := (name, organ)) not in self.__ftus_by_name_organ:
            self.__ftus_by_name_organ[key] = Annotation(name=name, parents=organ)
            self.__annotation_dict['FTUs'].append({
                'FTU Name': name,
                'Organ': organ,
                'Models': '',
                'Label': '',
                'Connected': 'YES' if connected else ''
            })

    def save(self):
    #==============
        Records = list[dict[str, str]]
        def record_sort(records: Records) -> Records:
            return sorted(records, key=lambda r: ((v := list(r.values()))[0].lower(), v[1].lower()))

        annotations = {
            name: record_sort(self.__annotation_dict[name])
                for name in sorted(self.__annotation_dict.keys())
        }
        with open(self.__annotation_file, 'w') as fp:
            fp.write(json.dumps(annotations, indent=4))
            fp.write('\n')

#===============================================================================

