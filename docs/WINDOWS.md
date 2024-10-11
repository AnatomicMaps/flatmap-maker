# This is for Ubuntu 18 running under WSL


**_Update for Python 3.12 and Poetry with SVG sources..._**

Convert to ReStructuredText...

## Development tools and libraries
```
$ sudo apt update
$ sudo apt install build-essential
$ sudo apt install zlib-dev
$ sudo apt install zlib-devel
$ sudo apt install sqlite3
$ sudo apt install libsqlite3-dev zlib1g-dev
```

## Python 3 and pip
```
$ sudo apt install software-properties-common
$ sudo add-apt-repository ppa:deadsnakes/ppa
$ sudo apt install python3.7
$ sudo apt install python3-pip
$ sudo pip3 install pipenv
```

## Node and npm
```
$ sudo apt install nodejs
$ sudo apt install npm
```

## Build and install tippecanoe
```
$ mkdir ~/build
$ cd ~/build
$ git clone https://github.com/mapbox/tippecanoe.git
$ cd tippecanoe/
$ make -j
$ sudo make install
```

## Flatmap code
```
$ mkdir ~/Flatmaps
```

## Server
```
$ cd ~/Flatmaps/
$ git clone https://github.com/dbrnz/flatmap-server.git server
$ cd server
$ pipenv install
$ mkdir flatmaps
```

## Maker
```
$ cd ~/Flatmaps/
$ git clone https://github.com/dbrnz/flatmap-mvt-maker.git maker
$ cd maker
$ pipenv install
```

## Viewer
```
$ cd ~/Flatmaps/
$ git clone https://github.com/dbrnz/flatmap-mvt-viewer.git viewer
$ cd viewer
$ npm install

$ vi src/endpoints.js
const MAP_ENDPOINT = 'http://localhost:4329/';

$ vi src/main.js
      // mapManager.loadMap('NCBITaxon:9606', 'map1');
      mapManager.loadMap('file://mnt/c/Users/Dave/build/maps/demo.pptx', 'map1', { annotatable: true, debug: true });
```

## Create tiles (image and vector)
```
$ cd ~/Flatmaps/maker
$ pipenv run python mapmaker.py --background-tiles --max-zoom 6 ../server/flatmaps demo /mnt/c/Users/Dave/build/maps/demo.pptx
```

## Annotations back into Powerpoint

After web browser annotation
```
$ cd ~/Flatmaps/maker
$ pipenv run python annotator.py --powerpoint /mnt/c/Users/Dave/build/maps/demo.pptx --update ../server/flatmaps demo
```

## Update map from Powerpoint

Without generating image tiles
```
$ cd ~/Flatmaps/maker
$ pipenv run python mapmaker.py ../server/flatmaps demo /mnt/c/Users/Dave/build/maps/demo.pptx
```

## Run map server

In a new shell:
```
$ cd ~/Flatmaps/server
$ pipenv run python bin/server.py --annotate
```

## Run map viewer

In a new shell:
```
$ cd ~/Flatmaps/viewer
$ npm start
```
