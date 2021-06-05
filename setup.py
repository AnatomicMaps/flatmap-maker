"""A setuptools based setup module.
See:
https://packaging.python.org/guides/distributing-packages-using-setuptools/
https://github.com/pypa/sampleproject
Modified by Madoshakalaka@Github (dependency links added)
"""

# Always prefer setuptools over distutils
from setuptools import setup, find_packages
import os.path

# Get mapmaker's version number
# See https://packaging.python.org/guides/single-sourcing-package-version/
def get_version(rel_path):
    here = os.path.abspath(os.path.dirname(__file__))
    with open(os.path.join(here, rel_path), "r") as fp:
        for line in fp.read().splitlines():
            if line.startswith("__version__"):
                delim = '"' if '"' in line else "'"
                return line.split(delim)[1]
        else:
            raise RuntimeError("Unable to find version string.")


setup(
    name="mapmaker",
    version=get_version("mapmaker/__init__.py"),
    description="Convert Powerpoint slides to Mapbox tiles",
    url="https://github.com/dbrnz/flatmap-maker",
    author="David Brooks",
    author_email="d.brooks@auckland.ac.nz",
    classifiers=[
        # How mature is this project? Common values are
        #   3 - Alpha
        #   4 - Beta
        #   5 - Production/Stable
        "Development Status :: 4 - Beta",
        # Indicate who your project is intended for
        "Intended Audience :: Developers",
        "Topic :: Software Development",
        # Pick your license as you wish
        "License :: OSI Approved :: Apache Software License",
        # Specify the Python versions you support here. In particular, ensure
        # that you indicate whether you support Python 2, Python 3 or both.
        # These classifiers are *not* checked by 'pip install'. See instead
        # 'python_requires' below.
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
    ],
    # This field adds keywords for your project which will appear on the
    # project page. What does your project relate to?
    #
    # Note that this is a string of words separated by whitespace, not a list.
    # keywords="TODO...",  # Optional
    #
    packages=find_packages(),
    package_data={"mapmaker": ["sources/powerpoint/presetShapeDefinitions.xml"]},
    python_requires=">=3.7, <4",
    install_requires=[
        "beziers==0.3.1",
        "certifi==2021.5.30",
        "chardet==4.0.0; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3, 3.4'",
        "click==8.0.1; python_version >= '3.6'",
        "cssselect2==0.4.1",
        "et-xmlfile==1.1.0; python_version >= '3.6'",
        "idna==2.10; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3'",
        "isodate==0.6.0",
        "lxml==4.6.3",
        "mbutil==0.3.0",
        "mercantile==1.2.1",
        "numpy==1.20.3",
        "opencv-python-headless==4.5.2.52",
        "openpyxl==3.0.7",
        "pillow==8.2.0; python_version >= '3.6'",
        "pybind11==2.6.2; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3, 3.4'",
        "pyclipper==1.2.1",
        "pymupdf==1.18.14",
        "pyparsing==2.4.7",
        "pyproj==3.1.0",
        "python-pptx==0.6.19",
        "pyyaml==5.4.1",
        "rdflib==5.0.0",
        "reportlab==3.5.67",
        "requests==2.25.1",
        "shapely==1.7.1",
        "six==1.16.0; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3'",
        "skia-python==87.2",
        "svglib==1.1.0",
        "tinycss2==1.1.0",
        "tqdm==4.61.0",
        "transforms3d==0.3.1",
        "urllib3==1.26.5; python_version >= '2.7' and python_version not in '3.0, 3.1, 3.2, 3.3, 3.4' and python_version < '4'",
        "webcolors==1.11.1",
        "webencodings==0.5.1",
        "xlsxwriter==1.4.3",
    ],
    extras_require={"dev": []},
    dependency_links=[],
    project_urls={
        "Bug Reports": "https://github.com/dbrnz/flatmap-maker/issues",
        "Source": "https://github.com/dbrnz/flatmap-maker/",
    },
)
