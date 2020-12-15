========
Overview
========

Mapmaker is a Python application for generating `Mapbox <https://www.mapbox.com/>`_ compatible tilesets from a set of Powerpoint slides.

Requirements
------------

* Python 3.8 with `pipenv <https://pipenv.pypa.io/en/latest/#install-pipenv-today>`_.
* `Tippecanoe <https://github.com/mapbox/tippecanoe#installation>`_.

Installation
------------

* Download the latest released Python wheel from https://github.com/dbrnz/flatmap-maker/releases/latest, currently ``mapmaker-0.11.0b4-py3-none-any.whl``.
* Create a directory in which to install ``mapmaker`` and change into it.

::

    $ pipenv install mapmaker-0.11.0b4-py3-none-any.whl

Running
-------

Command line help::

    $ pipenv run python -m mapmaker --help

::

    usage: mapmaker [-h] [-v]
                    [--log LOG_FILE] [-q] [--silent]
                    [--clean] [--background-tiles]
                    [--check-errors] [--save-beziers] [--save-drawml] [--save-geojson] [--tippecanoe]
                    [--initialZoom N] [--max-zoom N] [--min-zoom N]
                    [--refresh-labels] [--upload USER@SERVER]
                    --output OUTPUT --source SOURCE

    Generate a flatmap from its source manifest.

    optional arguments:
      -h, --help            show this help message and exit
      -v, --version         show program's version number and exit

    logging:
      --log LOG_FILE        append messages to a log file
      -q, --quiet           don't show progress bars
      --silent              suppress all messages to screen

    image tiling:
      --clean               Remove all files from generated map's directory before generating new map
      --background-tiles    generate image tiles of map's layers (may take a while...)

    diagnostics:
      --check-errors        check for errors without generating a map
      --save-beziers        Save Bezier curve segments as a feature property
      --save-drawml         save a slide's DrawML for debugging
      --save-geojson        Save GeoJSON files for each layer
      --tippecanoe          Show command used to run Tippecanoe

    zoom level:
      --initialZoom N       initial zoom level (defaults to 4)
      --max-zoom N          maximum zoom level (defaults to 10)
      --min-zoom N          minimum zoom level (defaults to 2)

    miscellaneous:
      --refresh-labels      Clear the label text cache before map making
      --upload USER@SERVER  Upload generated map to server

    required arguments:
      --output OUTPUT       base directory for generated flatmaps
      --source SOURCE       URL or directory path containing a flatmap manifest

For instance::

    $ pipenv run python -m mapmaker --output ./flatmaps   \
                                    --source ../PMR/rat
::

    Mapmaker 0.11.0.b4
    100%|█████████████████████████▉| 678/679
     98%|███████████████████████████▌| 65/66
    Adding details...
    Outputting GeoJson features...
    Layer: whole-rat
    100%|████████████████████████| 2477/2477
    Layer: whole-rat_details
    100%|██████████████████████████| 180/180
    Running tippecanoe...
    2657 features, 6439698 bytes of geometry, 25397 bytes of separate metadata, 485295 bytes of string pool
      99.9%  10/528/531
    Creating index and style files...
    Generated map for NCBITaxon:10114