import sys
import os
from setuptools import setup, find_packages

"""
This file should called to install the package.
"""

REPO_DIR = os.getcwd()


def getPlatformInfo():
    """
    Identify platform
    """
    if "linux" in sys.platform:
        platform = "linux"
    elif "darwin" in sys.platform:
        platform = "darwin"
    elif "win32" in sys.platform:
        platform = "windows"
    else:
        raise Exception("Platform '%s' is unsupported!" % sys.platform)

    if sys.maxsize > 2**32:
        bitness = "64"
    else:
        bitness = "32"

    return platform, bitness


platform, bitness = getPlatformInfo()

# Call the setup process
os.chdir(REPO_DIR)
setup(
    name = 'ragaz',
    version = "0.1.0-alpha",
    packages = find_packages(),
    package_data = {
        '': ['README.md', 'LICENSE']},
    description = 'Ragaz is a fast, safe and powerful pythonic language which aims allow you to create simple scripts to complex systems in a code easier to read, write and maintain than other system languages with the same purpose.',
    author='David Ragazzi',
    author_email='david_ragazzi@hotmail.com',
    url='https://github.com/ragazzi-robotics/ragaz/',
    classifiers=[
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools'
    ],
    install_requires = [
        "rply==0.7.8",
        "llvmlite==0.39.1"],
    long_description = """Ragaz is a fast, safe and powerful pythonic language which aims allow you to create simple scripts to complex systems in a code easier to read, write and maintain than other system languages with the same purpose.
For more information, see GitHub page (https://github.com/ragazzi-robotics/ragaz/)."""
)
