#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020 - 2023 David Brooks
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

"""
Slashes aren't valid in SVG (XML) IDs so we replace them with periods (``.``)

In practice, feature IDs are have the form ``LAYER_NAME/Slide-N/NNNNN`` and
won't contain any embedded periods.
"""
def svg_id(shape_id: str) -> str:
#================================
    shape_id = shape_id.split('/')[-1]
    if shape_id.startswith('SHAPE_'):
        shape_id = f'ID-{shape_id[6:].zfill(8)}'
    return shape_id

def name_from_id(id):
#====================
    return id.capitalize().replace('/', ' - ').replace('_', ' ')

#===============================================================================

def css_class(cls):
#==================
    return cls.replace(':', '-')

#===============================================================================
