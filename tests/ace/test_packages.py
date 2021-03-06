# vim: sw=4:ts=4:et:cc=120

import os
import os.path

import pytest
import yaml

from ace.module.base import AnalysisModule
from ace.packages import load_packages, load_package_from_dict, ACEPackage


class TestModule1(AnalysisModule):
    pass


class TestModule2(AnalysisModule):
    pass


sample_yaml = """
---
  name: Sample Package
  description: Sample Description
  version: 1.0.0

  modules:
    - tests.ace.test_packages.TestModule1
    - tests.ace.test_packages.TestModule2

  services:
    - core_modules.services.SomeCoolService

  config:
    core_modules:
      file_analysis:
        file_type:
          file_path:
            value: file
            description: Path to the file binary.
          some_param: 
            value: some_value
            description: A good description people can understand.
        file_hash:
          some_param: other_value # no value or key, so it just defaults to an empty description
      url_analysis:
        crawlphish:
          max_requests:
            value: 4096
            description: Maximum number of simultaneous requests.
          max_size: 
            value: 35 MB
            description: >
              Maximum size of data downloaded from target URL. 
              An value by itself is interpreted as bytes.
              You can also specify KB, MB or GB.
          use_proxy: False
          use_tor: False
          # this stuff maps into the configuration settings like this:
          # /core_modules/url_analysis/crawlphish/max_requests
          # /core_modules/url_analysis/crawlphish/use_proxy
          # /core_modules/url_analysis/crawlphish/use_tor
          # /core_modules/url_analysis/crawlphish/custom_headers
          custom_headers:
            - "User-Agent: blah blah blah"
            - "Some-Header: blah blah boo"
"""


def verify_loaded_package(package: ACEPackage):
    assert isinstance(package, ACEPackage)
    # assert package.source == "test"
    assert package.name == "Sample Package"
    assert package.description == "Sample Description"
    assert package.version == "1.0.0"
    assert len(package.modules) == 2

    for i in range(2):
        assert issubclass(package.modules[i], AnalysisModule)
        module_instance = package.modules[i]()
        assert isinstance(module_instance, AnalysisModule)


@pytest.mark.unit
def test_load_package_from_dict():
    verify_loaded_package(load_package_from_dict(yaml.safe_load(sample_yaml), "test"))


@pytest.mark.unit
def test_load_packages(tmpdir):
    package_dir = str(tmpdir / "packages")
    os.mkdir(package_dir)
    path = os.path.join(package_dir, "test.yml")

    with open(path, "w") as fp:
        fp.write(sample_yaml)

    packages = load_packages(package_dir)
    assert len(packages) == 1
    verify_loaded_package(packages[0])
