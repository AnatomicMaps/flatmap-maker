DRC Paper
=========

Flatmaps
--------

Flatmaps are interactive maps for exploring anatomical information over a large range of length scales, using the same interfaces as used by geographical maps. A flatmap is defined by a set of shapes in MS Powerpoint slide along with additional properties specified in JSON. These shapes and properties are used by a Python application to construct GeoJSON features, with Powerpoint coordinates converted to WGS84/Pseudo-Mercator geographical coordinates. Mapbox vector tiles are generated from the GeoJSON and separately, background image tiles are generated from a PDF of the original Powerpoint slide. Generated maps are provided to a browser-based flatmap viewer via a Web Map Tile Service (WMTS).

