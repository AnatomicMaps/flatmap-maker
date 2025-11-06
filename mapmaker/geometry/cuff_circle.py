#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020 - 2024 David Brooks
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

from shapely import LineString
import numpy as np

#===============================================================================

def cuff_circle(cx: float, cy: float, path_num: int, num_dashes=20, dash_ratio=0.5) -> LineString:
    r = 5000 * (1 + np.log(path_num + 1))
    angles = np.linspace(0, 2 * np.pi, num_dashes + 1)
    coords = []
    for i in range(num_dashes):
        start_angle = angles[i]
        end_angle = angles[i] + (angles[i+1] - angles[i]) * dash_ratio
        start = (cx + r * np.cos(start_angle), cy + r * np.sin(start_angle))
        end = (cx + r * np.cos(end_angle), cy + r * np.sin(end_angle))
        coords.append(start)
        coords.append(end)
    return LineString(coords)


#===============================================================================
