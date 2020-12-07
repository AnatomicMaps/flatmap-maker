#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019, 2020  David Brooks
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

import requests

#===============================================================================

def get_workspace(exposure):
    r = requests.get(exposure, headers={'Accept': 'application/vnd.physiome.pmr2.json.1'})
    if r.status_code != requests.codes.ok:
        r.raise_for_status()
    exposure_info = '{}/exposure_info'.format(exposure)
    response = r.json()
    if response['collection']['href'] == exposure_info:
        item = [i for i in response['collection']['items']
                  if i['href'] == '{}/exposure_info'.format(exposure)][0]
        commit = [d['value'] for d in item['data']
                    if d['name'] == 'commit_id'][0]
        href = [l['href'] for l in response['collection']['links'] if l['rel'] == 'via'][0]
        return '{}/rawfile/{}'.format(href, commit)

#===============================================================================
